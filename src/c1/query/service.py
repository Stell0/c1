"""Request-scoped, bounded queries over a fully authorized resource selection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from collections.abc import Iterable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Literal, cast

from c1.authorization.principal import Principal
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.model.records import C1, RDF
from c1.model.references import is_independent_reference
from c1.model.time import TimeBoundary, TimeInterval
from c1.query.compile import fetch_records
from c1.query.cursor import CursorCodec, CursorError
from c1.query.export import export_authorized
from c1.query.filters import (
    AssertionFilters,
    QueryFilters,
    evaluate_assertion,
    evaluate_entity,
    filter_digest,
    order_key,
)
from c1.query.index import CurrentBindingIndex
from c1.query.plan import AuthorizedPlan, AuthorizedSelection, QueryPlanError
from c1.query.traverse import traverse_authorized
from c1.storage.mapping import storage_id

if TYPE_CHECKING:
    from c1.runtime import Runtime

TIME = "http://www.w3.org/2006/time#"
IDENTITY = "urn:c1:ns:identity#"
_PRESENTABLE = {
    C1 + "Entity",
    C1 + "Assertion",
    C1 + "Source",
    C1 + "Evidence",
}
_REVISION = re.compile(r"(?:branch:|commit:)?[A-Za-z0-9_-]+\Z")


class AuthorizedRecords(dict[str, NodeRecord]):
    """Rendered nodes with private metadata about withheld time boundaries."""

    def __init__(
        self,
        records: dict[str, NodeRecord],
        hidden_bounds: dict[str, frozenset[str]],
    ) -> None:
        super().__init__(records)
        self.hidden_bounds = hidden_bounds


def _iri(node: NodeRecord, predicate: str) -> str | None:
    return next((v for v in node.properties.get(predicate, ()) if isinstance(v, str)), None)


def _text(node: NodeRecord, predicate: str) -> str | None:
    return next(
        (v.lexical for v in node.properties.get(predicate, ()) if isinstance(v, LiteralValue)),
        None,
    )


def _boundary(node: NodeRecord) -> TimeBoundary | None:
    state = _text(node, C1 + "boundaryState")
    if state not in {"known", "unknown", "unbounded"}:
        return None
    if state != "known":
        return TimeBoundary(state=cast(Literal["unknown", "unbounded"], state))
    for kind in ("dateTimeStamp", "dateTime", "date", "gYearMonth", "gYear"):
        datatype = "http://www.w3.org/2001/XMLSchema#" + kind
        property_name = "inXSD" + (kind if kind.startswith("g") else kind[0].upper() + kind[1:])
        value = next(
            (
                item
                for item in node.properties.get(TIME + property_name, ())
                if isinstance(item, LiteralValue)
            ),
            None,
        )
        if value is not None:
            return TimeBoundary(state="known", lexical=value.lexical, datatype=datatype)
    return None


def _intervals(records: AuthorizedRecords) -> dict[str, TimeInterval]:
    boundaries = {
        identifier: boundary
        for identifier, node in records.items()
        if C1 + "TimeBoundary" in node.types
        if (boundary := _boundary(node)) is not None
    }
    result: dict[str, TimeInterval] = {}
    for identifier, node in records.items():
        if C1 + "TimeInterval" not in node.types:
            continue
        start_id = _iri(node, TIME + "hasBeginning")
        end_id = _iri(node, TIME + "hasEnd")
        start = (
            boundaries.get(start_id)
            if start_id
            else TimeBoundary(
                state="unknown"
                if TIME + "hasBeginning" in records.hidden_bounds.get(identifier, ())
                else "unbounded"
            )
        )
        end = (
            boundaries.get(end_id)
            if end_id
            else TimeBoundary(
                state="unknown"
                if TIME + "hasEnd" in records.hidden_bounds.get(identifier, ())
                else "unbounded"
            )
        )
        if start is not None and end is not None:
            result[identifier] = TimeInterval(start=start, end=end)
    return result


def _record_references_visible(
    node: NodeRecord,
    readable: frozenset[str],
    instance_base: str,
    registry: ProfileRegistry,
) -> bool:
    """Identity decisions and relationship assertions cannot expose hidden IDs."""
    if C1 + "Assertion" in node.types:
        subject = _iri(node, RDF + "subject")
        obj = _iri(node, RDF + "object")
        interval = _iri(node, C1 + "validDuring")
        predicate = _iri(node, RDF + "predicate")
        definition = registry.predicates.get(predicate) if predicate else None
        relationship = definition is not None and any(
            item in registry.classes for item in definition.ranges
        )
        return (
            subject in readable
            and (interval is None or interval in readable)
            and (
                obj is None
                or (not relationship and not obj.startswith(instance_base))
                or obj in readable
            )
        )
    if IDENTITY + "Redirect" in node.types:
        return all(_iri(node, IDENTITY + part) in readable for part in ("from", "to", "resolution"))
    if C1 + "ResolutionRecord" in node.types:
        return all(
            value in readable
            for value in node.properties.get(C1 + "candidate", ())
            if isinstance(value, str)
        )
    if C1 + "Evidence" in node.types:
        return all(
            _iri(node, predicate) in readable
            for predicate in (C1 + "assertionRef", "http://www.w3.org/ns/oa#hasSource")
        )
    return True


class QueryService:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        settings = runtime.settings
        self.planner = AuthorizedSelection(
            runtime.journal,
            runtime.fga,
            runtime.plane,
            index=CurrentBindingIndex(runtime.journal),
            candidate_limit=settings.query_candidate_limit,
            max_readable_scopes=settings.max_readable_scopes,
            time_budget_ms=settings.query_time_budget_ms,
        )

    @property
    def codec(self) -> CursorCodec:
        if not self.runtime.settings.cursor_secret:
            raise QueryPlanError(503, "C1-QY-054", "cursor_configuration_unavailable")
        return CursorCodec(self.runtime.settings.cursor_secret)

    async def selection(
        self,
        principal: Principal,
        *,
        scope_ids: Iterable[str] | None = None,
        deadline: float,
    ) -> tuple[AuthorizedPlan, dict[str, NodeRecord]]:
        plan = await self.planner.build(
            principal,
            scope_ids=frozenset(scope_ids) if scope_ids else None,
            deadline=deadline,
        )
        return plan, {}

    async def records(
        self,
        plan: AuthorizedPlan,
        revision: str,
        *,
        deadline: float,
    ) -> AuthorizedRecords:
        try:
            async with asyncio.timeout_at(deadline):
                fetched = await fetch_records(
                    self.runtime.knowledge,
                    self.runtime.registry,
                    list(plan.authorized_ids),
                    revision=revision,
                )
            # A backend must never return an unrequested ID, even if its class
            # query accidentally broadens; fail rather than filter a leak.
            if not set(fetched).issubset(plan.authorized_ids):
                raise QueryPlanError(503, "C1-QY-054", "unexpected_backend_selection")
            visible_ids = set(fetched)
            while True:
                denied = {
                    identifier
                    for identifier in visible_ids
                    if not _record_references_visible(
                        fetched[identifier],
                        frozenset(visible_ids),
                        self.runtime.settings.instance_base,
                        self.runtime.registry,
                    )
                }
                if not denied:
                    break
                visible_ids.difference_update(denied)
            result: dict[str, NodeRecord] = {}
            hidden_bounds: dict[str, frozenset[str]] = {}
            for identifier in visible_ids:
                node = fetched[identifier]
                properties = {
                    predicate: visible_values
                    for predicate, values in node.properties.items()
                    if (
                        visible_values := [
                            value
                            for value in values
                            if not isinstance(value, str)
                            or not is_independent_reference(predicate, self.runtime.registry)
                            or value in visible_ids
                        ]
                    )
                }
                if C1 + "TimeInterval" in node.types:
                    withheld = frozenset(
                        predicate
                        for predicate in (TIME + "hasBeginning", TIME + "hasEnd")
                        if node.properties.get(predicate) and not properties.get(predicate)
                    )
                    if withheld:
                        hidden_bounds[identifier] = withheld
                result[identifier] = node.model_copy(update={"properties": properties})
            return AuthorizedRecords(result, hidden_bounds)
        except TimeoutError as exc:
            raise QueryPlanError(503, "C1-QY-053", "time_budget") from exc

    async def _revision(
        self, filters: QueryFilters, principal: Principal
    ) -> tuple[str, tuple[str, str] | None]:
        digest = filter_digest(filters)
        if filters.cursor:
            try:
                cursor = self.codec.decode(
                    filters.cursor,
                    principal=principal.id,
                    revision=filters.revision,
                    filter_digest=digest,
                    order=filters.order,
                )
            except CursorError as exc:
                raise QueryPlanError(400, "C1-QY-004", "invalid_cursor") from exc
            return cursor.revision, cursor.last_key
        return filters.revision or await self.runtime.knowledge.head(), None

    async def _recorded_times(
        self, records: Iterable[NodeRecord], revision: str, *, deadline: float
    ) -> dict[str, str]:
        """Resolve last recorded timestamps on the selected commit's ancestry.

        TerminusDB's pinned historical document-history route fails with 500.
        Its commit-bound log returns exactly the selected ancestors, while
        per-document history supplies each record's changed commits.
        """
        if not _REVISION.fullmatch(revision):
            raise QueryPlanError(400, "C1-QY-001", "invalid_revision")
        commit = revision.removeprefix("branch:").removeprefix("commit:")
        storage = self.runtime.knowledge
        path = f"/api/log/{storage._database_path}/local/commit/{commit}"
        ancestors: set[str] = set()
        try:
            async with asyncio.timeout_at(deadline):
                for start in range(0, 10000, 100):
                    response = await storage._request(
                        "GET", path, params={"start": start, "count": 100}
                    )
                    page = response.json()
                    if not isinstance(page, list) or not all(
                        isinstance(item, dict) and isinstance(item.get("identifier"), str)
                        for item in page
                    ):
                        raise ValueError("invalid commit log")
                    ancestors.update(str(item["identifier"]) for item in page)
                    if len(page) < 100:
                        break
                else:
                    raise QueryPlanError(422, "C1-QY-052", "commit_history_too_large")
                semaphore = asyncio.Semaphore(8)

                async def one(node: NodeRecord) -> tuple[str, str]:
                    async with semaphore:
                        definition = self.runtime.registry.primary_class(node.types)
                        identifier = storage_id(
                            node, definition, self.runtime.settings.instance_base
                        )
                        entries = await storage.history(identifier)
                        for item in entries:
                            if item.get("identifier") in ancestors:
                                timestamp = item.get("timestamp")
                                if isinstance(timestamp, str):
                                    return node.id, timestamp
                                if (
                                    isinstance(timestamp, (int, float))
                                    and math.isfinite(timestamp)
                                    and timestamp >= 0
                                ):
                                    return node.id, f"{timestamp:020.6f}"
                                raise ValueError("invalid history timestamp")
                        raise ValueError("record absent from selected ancestry")

                return dict(await asyncio.gather(*(one(node) for node in records)))
        except TimeoutError as exc:
            raise QueryPlanError(503, "C1-QY-053", "time_budget") from exc
        except QueryPlanError:
            raise
        except Exception as exc:
            raise QueryPlanError(503, "C1-QY-054", "history_unavailable") from exc

    async def entities(self, principal: Principal, filters: QueryFilters) -> dict[str, Any]:
        deadline = time.monotonic() + self.runtime.settings.query_time_budget_ms / 1000
        revision, after = await self._revision(filters, principal)
        plan, _ = await self.selection(principal, scope_ids=filters.scope_ids, deadline=deadline)
        records = await self.records(plan, revision, deadline=deadline)
        entities = [node for node in records.values() if C1 + "Entity" in node.types]
        assertions = tuple(node for node in records.values() if C1 + "Assertion" in node.types)
        keywords = {
            identifier: node for identifier, node in records.items() if C1 + "Keyword" in node.types
        }
        intervals = _intervals(records)
        readable_entities = frozenset(node.id for node in entities)
        matches: list[tuple[NodeRecord, tuple[str, ...], str]] = []
        for node in entities:
            result = evaluate_entity(
                node,
                filters,
                keywords_by_id=keywords,
                assertions=assertions,
                readable_entity_ids=readable_entities,
                intervals_by_id=intervals,
                scope_id=plan.scope_by_id.get(node.id),
            )
            if result.included:
                matches.append((node, result.matched_filters, result.status))
        recorded = (
            await self._recorded_times(
                (node for node, _, _ in matches), revision, deadline=deadline
            )
            if filters.order == "recorded" and matches
            else {}
        )
        selected = [
            (
                order_key(node, filters.order, recorded_at=recorded.get(node.id)),
                node,
                matched,
                status,
            )
            for node, matched, status in matches
        ]
        selected.sort(key=lambda item: item[0])
        count = len(selected)
        if after is not None:
            selected = [item for item in selected if item[0] > after]
        page = selected[: filters.limit]
        next_cursor = (
            self.codec.encode(
                principal=principal.id,
                revision=revision,
                filter_digest=filter_digest(filters),
                order=filters.order,
                last_key=page[-1][0],
            )
            if page and len(selected) > filters.limit
            else None
        )
        await self.planner.finalize(principal, plan, deadline=deadline)
        return {
            "instance": self.runtime.settings.instance_id,
            "revision": revision,
            "profile_versions": {
                name: profile.version for name, profile in self.runtime.registry.profiles.items()
            },
            "order": filters.order,
            "limit": filters.limit,
            "count": count,
            "items": [node.model_dump(mode="json") for _, node, _, _ in page],
            "indeterminate": [
                {"id": node.id, "rule": "unknown_validity"}
                for _, node, _, status in page
                if status == "indeterminate"
            ],
            "explain": {node.id: list(matched) for _, node, matched, _ in page},
            "next_cursor": next_cursor,
        }

    async def assertions(
        self,
        principal: Principal,
        filters: AssertionFilters,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.runtime.settings.query_time_budget_ms / 1000
        serialized = filters.model_dump(mode="json", exclude={"revision", "limit", "cursor"})
        digest = hashlib.sha256(
            json.dumps(serialized, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        after: tuple[str, str] | None = None
        revision = filters.revision
        if filters.cursor:
            try:
                position = self.codec.decode(
                    filters.cursor,
                    principal=principal.id,
                    revision=revision,
                    filter_digest=digest,
                    order="id",
                )
            except CursorError as exc:
                raise QueryPlanError(400, "C1-QY-004", "invalid_cursor") from exc
            revision, after = position.revision, position.last_key
        plan, _ = await self.selection(principal, deadline=deadline)
        selected_revision = revision or await self.runtime.knowledge.head()
        records = await self.records(plan, selected_revision, deadline=deadline)
        intervals = _intervals(records)
        items: list[NodeRecord] = []
        indeterminate: list[dict[str, str]] = []
        matched_by_id: dict[str, list[str]] = {}
        for node in records.values():
            if C1 + "Assertion" not in node.types:
                continue
            interval_id = _iri(node, C1 + "validDuring")
            result = evaluate_assertion(
                node, filters, interval=intervals.get(interval_id) if interval_id else None
            )
            if result.included:
                items.append(node)
                matched_by_id[node.id] = list(result.matched_filters)
                if result.status == "indeterminate":
                    indeterminate.append({"id": node.id, "rule": "unknown_validity"})
        items.sort(key=lambda node: node.id)
        count = len(items)
        if after:
            items = [node for node in items if (node.id, node.id) > after]
        page = items[: filters.limit]
        next_cursor = (
            self.codec.encode(
                principal=principal.id,
                revision=selected_revision,
                filter_digest=digest,
                order="id",
                last_key=(page[-1].id, page[-1].id),
            )
            if page and len(items) > filters.limit
            else None
        )
        await self.planner.finalize(principal, plan, deadline=deadline)
        return {
            "instance": self.runtime.settings.instance_id,
            "revision": selected_revision,
            "profile_versions": {
                name: profile.version for name, profile in self.runtime.registry.profiles.items()
            },
            "order": "id",
            "limit": filters.limit,
            "count": count,
            "items": [node.model_dump(mode="json") for node in page],
            "explain": {node.id: matched_by_id[node.id] for node in page},
            "indeterminate": [
                item for item in indeterminate if item["id"] in {node.id for node in page}
            ],
            "next_cursor": next_cursor,
        }

    async def list_kind(
        self,
        principal: Principal,
        kind: str,
        *,
        revision: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if kind not in {"Source", "Evidence"} or not 1 <= limit <= 200:
            raise QueryPlanError(422, "C1-QY-010", "invalid_limit")
        deadline = time.monotonic() + self.runtime.settings.query_time_budget_ms / 1000
        digest = hashlib.sha256(("kind:" + kind).encode()).hexdigest()
        after: tuple[str, str] | None = None
        if cursor:
            try:
                position = self.codec.decode(
                    cursor,
                    principal=principal.id,
                    revision=revision,
                    filter_digest=digest,
                    order="id",
                )
            except CursorError as exc:
                raise QueryPlanError(400, "C1-QY-004", "invalid_cursor") from exc
            revision, after = position.revision, position.last_key
        selected_revision = revision or await self.runtime.knowledge.head()
        plan, _ = await self.selection(principal, deadline=deadline)
        records = await self.records(plan, selected_revision, deadline=deadline)
        items = sorted(
            (node for node in records.values() if C1 + kind in node.types),
            key=lambda node: node.id,
        )
        count = len(items)
        if after:
            items = [node for node in items if (node.id, node.id) > after]
        page = items[:limit]
        next_cursor = (
            self.codec.encode(
                principal=principal.id,
                revision=selected_revision,
                filter_digest=digest,
                order="id",
                last_key=(page[-1].id, page[-1].id),
            )
            if page and len(items) > limit
            else None
        )
        await self.planner.finalize(principal, plan, deadline=deadline)
        return {
            "instance": self.runtime.settings.instance_id,
            "revision": selected_revision,
            "profile_versions": {
                name: profile.version for name, profile in self.runtime.registry.profiles.items()
            },
            "order": "id",
            "limit": limit,
            "count": count,
            "items": [node.model_dump(mode="json") for node in page],
            "explain": {node.id: ["type"] for node in page},
            "next_cursor": next_cursor,
        }

    async def entity(
        self, principal: Principal, identifier: str, *, revision: str | None = None
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.runtime.settings.query_time_budget_ms / 1000
        plan, _ = await self.selection(principal, deadline=deadline)
        selected_revision = revision or await self.runtime.knowledge.head()
        records = await self.records(plan, selected_revision, deadline=deadline)
        node = records.get(identifier)
        if node is None or C1 + "Entity" not in node.types:
            raise QueryPlanError(404, "C1-QY-404", "not_found")
        result = node.model_dump(mode="json")
        if _text(node, C1 + "lifecycle") == "superseded":
            redirects = [
                candidate
                for candidate in records.values()
                if IDENTITY + "Redirect" in candidate.types
                and _iri(candidate, IDENTITY + "from") == identifier
                and _iri(candidate, IDENTITY + "to") in records
                and _iri(candidate, IDENTITY + "resolution") in records
            ]
            if len(redirects) != 1:
                raise QueryPlanError(404, "C1-QY-404", "not_found")
            result["redirected_to"] = _iri(redirects[0], IDENTITY + "to")
        await self.planner.finalize(principal, plan, deadline=deadline)
        return result

    async def export(
        self,
        principal: Principal,
        *,
        revision: str | None = None,
        types: tuple[str, ...] = (),
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise QueryPlanError(422, "C1-QY-010", "invalid_limit")
        deadline = time.monotonic() + self.runtime.settings.query_time_budget_ms / 1000
        digest = hashlib.sha256(json.dumps(sorted(types)).encode()).hexdigest()
        after: tuple[str, str] | None = None
        if cursor:
            try:
                position = self.codec.decode(
                    cursor,
                    principal=principal.id,
                    revision=revision,
                    filter_digest=digest,
                    order="id",
                )
            except CursorError as exc:
                raise QueryPlanError(400, "C1-QY-004", "invalid_cursor") from exc
            revision, after = position.revision, position.last_key
        selected_revision = revision or await self.runtime.knowledge.head()
        plan, _ = await self.selection(principal, deadline=deadline)
        records = await self.records(plan, selected_revision, deadline=deadline)
        selected = sorted(
            (
                node
                for node in records.values()
                if (not types or set(types) & set(node.types))
                and bool(_PRESENTABLE & set(node.types))
            ),
            key=lambda node: node.id,
        )
        count = len(selected)
        if after:
            selected = [node for node in selected if (node.id, node.id) > after]
        page = selected[:limit]
        payload = export_authorized(page, self.runtime.registry, authorized_ids=frozenset(records))
        next_cursor = (
            self.codec.encode(
                principal=principal.id,
                revision=selected_revision,
                filter_digest=digest,
                order="id",
                last_key=(page[-1].id, page[-1].id),
            )
            if page and len(selected) > limit
            else None
        )
        await self.planner.finalize(principal, plan, deadline=deadline)
        return {
            "instance": self.runtime.settings.instance_id,
            "revision": selected_revision,
            "profile_versions": {
                name: profile.version for name, profile in self.runtime.registry.profiles.items()
            },
            "order": "id",
            "limit": limit,
            "count": count,
            "snapshot": payload,
            "explain": {node.id: ["type"] for node in page},
            "next_cursor": next_cursor,
        }

    async def catalog(self, principal: Principal) -> dict[str, Any]:
        deadline = time.monotonic() + self.runtime.settings.query_time_budget_ms / 1000
        plan, _ = await self.selection(principal, deadline=deadline)
        revision = await self.runtime.knowledge.head()
        records = await self.records(plan, revision, deadline=deadline)
        classes = sorted(
            {
                kind
                for node in records.values()
                for kind in node.types
                if kind in self.runtime.registry.classes
            }
        )
        predicates = sorted(
            {
                predicate
                for kind in classes
                for predicate in self.runtime.registry.classes[kind].properties
            }
        )
        await self.planner.finalize(principal, plan, deadline=deadline)
        return {
            "instance": self.runtime.settings.instance_id,
            "revision": revision,
            "profile_versions": {
                name: profile.version for name, profile in self.runtime.registry.profiles.items()
            },
            "classes": classes,
            "predicates": predicates,
            "limits": {
                "page_default": 50,
                "page_max": 200,
                "query_candidates": self.runtime.settings.query_candidate_limit,
                "readable_scopes": self.runtime.settings.max_readable_scopes,
                "traversal_depth": 3,
                "traversal_nodes": 500,
                "traversal_edges": 2000,
                "time_budget_ms": self.runtime.settings.query_time_budget_ms,
            },
        }

    async def neighborhood(
        self,
        principal: Principal,
        start_id: str,
        *,
        predicates: frozenset[str],
        direction: str = "out",
        depth: int = 1,
        limit: int = 200,
        revision: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 2000 or not 1 <= depth <= 3:
            raise QueryPlanError(422, "C1-QY-010", "invalid_traversal_limit")
        if direction not in {"out", "in", "both"}:
            raise QueryPlanError(400, "C1-QY-001", "invalid_direction")
        deadline = time.monotonic() + self.runtime.settings.query_time_budget_ms / 1000
        digest = hashlib.sha256(
            json.dumps(
                {
                    "start_id": start_id,
                    "predicates": sorted(predicates),
                    "direction": direction,
                    "depth": depth,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        offset = 0
        cursor_context: dict[str, str] | None = None
        position = None
        if cursor:
            try:
                position = self.codec.decode(
                    cursor,
                    principal=principal.id,
                    revision=revision,
                    filter_digest=digest,
                    order="traversal",
                )
                revision = position.revision
                if not position.last_key[0].isdigit():
                    raise ValueError("invalid traversal offset")
                offset = int(position.last_key[0])
                if not 0 < offset < 2000:
                    raise ValueError("invalid traversal offset")
                cursor_context = json.loads(position.last_key[1])
                if (
                    not isinstance(cursor_context, dict)
                    or set(cursor_context) != {"head", "selection"}
                    or not all(isinstance(value, str) for value in cursor_context.values())
                ):
                    raise ValueError("invalid traversal context")
            except (CursorError, ValueError, TypeError, KeyError) as exc:
                raise QueryPlanError(400, "C1-QY-004", "invalid_cursor") from exc
        plan, _ = await self.selection(principal, deadline=deadline)
        selection_fingerprint = hashlib.sha256(
            json.dumps(plan.authorized_ids, separators=(",", ":")).encode()
        ).hexdigest()
        if cursor_context is not None and cursor_context != {
            "head": plan.workflow_head,
            "selection": selection_fingerprint,
        }:
            raise QueryPlanError(409, "C1-QY-051", "restart_required")
        selected_revision = revision or await self.runtime.knowledge.head()
        records = await self.records(plan, selected_revision, deadline=deadline)
        if start_id not in records or C1 + "Entity" not in records[start_id].types:
            raise QueryPlanError(404, "C1-QY-404", "not_found")
        try:
            result = traverse_authorized(
                records.values(),
                start_id,
                predicates=predicates,
                direction=cast(Literal["out", "in", "both"], direction),
                depth=depth,
                limit=min(2000, offset + limit),
                deadline=deadline,
            )
        except TimeoutError as exc:
            raise QueryPlanError(503, "C1-QY-053", "time_budget") from exc
        except (KeyError, ValueError) as exc:
            raise QueryPlanError(409, "C1-QY-051", "restart_required") from exc
        if offset > len(result.edges):
            raise QueryPlanError(409, "C1-QY-051", "restart_required")
        page_edges = result.edges[offset:]
        prior_nodes = {start_id}
        for edge in result.edges[:offset]:
            prior_nodes.update((edge.subject, edge.object))
        page_nodes = tuple(node for node in result.nodes if node.id not in prior_nodes)
        next_cursor = None
        if result.checkpoint is not None:
            next_cursor = self.codec.encode(
                principal=principal.id,
                revision=selected_revision,
                filter_digest=digest,
                order="traversal",
                last_key=(
                    str(offset + len(page_edges)),
                    json.dumps(
                        {"head": plan.workflow_head, "selection": selection_fingerprint},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )
        await self.planner.finalize(principal, plan, deadline=deadline)
        return {
            "instance": self.runtime.settings.instance_id,
            "revision": selected_revision,
            "nodes": [node.model_dump(mode="json") for node in page_nodes],
            "edges": [asdict(edge) for edge in page_edges],
            "truncated": result.truncated,
            "budget": asdict(result.budget),
            "next_cursor": next_cursor,
        }
