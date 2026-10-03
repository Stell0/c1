"""One authorized snapshot supplies deterministic, immediately usable context."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from typing import TYPE_CHECKING, Any

from c1.authorization.principal import Principal
from c1.context.budget import build_page, prepare_units
from c1.context.errors import ContextError
from c1.context.profiles import SoftwareContextProfile
from c1.context.request import ContextRequest, request_digest
from c1.context.resolve import primary_label, resolve_anchor
from c1.context.select import select_context
from c1.context.software_service import build_software_context
from c1.context.topics import resolve_topics
from c1.context.units import build_units
from c1.model.diagnostics import ProfileError
from c1.model.nodes import NodeRecord
from c1.model.records import RDF
from c1.query.cursor import CursorError
from c1.query.plan import AuthorizedPlan
from c1.storage.schema import profile_digest

if TYPE_CHECKING:
    from c1.runtime import Runtime

ORDER = "context-units-v1"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _label(node: NodeRecord) -> str:
    return primary_label(node)


def _orientation(selection: dict[str, Any], records: dict[str, NodeRecord]) -> list[dict[str, Any]]:
    result = []
    for path in selection["orientation"]:
        nodes = [
            {
                "id": identifier,
                "label": _label(records[identifier]),
                "types": sorted(records[identifier].types),
            }
            for identifier in path["node_ids"]
        ]
        edges = []
        for identifier in path["path"]:
            assertion = records[identifier]
            predicate = next(
                value for value in assertion.properties[RDF + "predicate"] if isinstance(value, str)
            )
            edges.append(
                {
                    "assertion_id": identifier,
                    "predicate": predicate,
                    "subject": assertion.properties[RDF + "subject"][0],
                    "object": assertion.properties[RDF + "object"][0],
                }
            )
        result.append(
            {"nodes": nodes, "edges": edges, "node_ids": path["node_ids"], "path": path["path"]}
        )
    return result


def _checkpoint(
    units: list[dict[str, Any]],
    public_units: list[dict[str, Any]],
    offset: int,
    interpretation: dict[str, Any],
    records: dict[str, NodeRecord],
    plan: AuthorizedPlan,
    common_dependencies: frozenset[str] = frozenset(),
) -> str:
    dependencies = {
        identifier for unit in units[:offset] for identifier in unit.get("_dependencies", [])
    }
    dependencies.add(interpretation["anchor"]["id"])
    # Software-task interpretations have no topics (M12 fix: a truncated
    # software page needs a continuation checkpoint too).
    dependencies.update(topic["id"] for topic in interpretation.get("topics", []))
    dependencies.update(common_dependencies)
    # Policy identifiers are hashed, never returned. Project only dependencies
    # of this prefix: an unrelated hidden write must not affect continuation.
    return _digest(
        {
            "interpretation": interpretation,
            "units": public_units[:offset],
            "bindings": {
                identifier: plan.scope_by_id[identifier]
                for identifier in sorted(dependencies)
                if identifier in records
            },
        }
    )


class ContextService:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    async def build(self, principal: Principal, request: ContextRequest) -> dict[str, Any]:
        deadline = time.monotonic() + self.runtime.settings.query_time_budget_ms / 1000
        try:
            async with asyncio.timeout_at(deadline):
                return await self._build(principal, request, deadline=deadline)
        except TimeoutError as exc:
            raise ContextError(503, "C1-CX-014", "time_budget") from exc

    async def _build(
        self, principal: Principal, request: ContextRequest, *, deadline: float
    ) -> dict[str, Any]:
        catalog = self.runtime.context_catalog()
        try:
            profile = catalog.get_any(request.profile, request.profile_version)
        except ProfileError as exc:
            raise ContextError(400, "C1-CX-002", "unknown_context_profile") from exc
        if isinstance(profile, SoftwareContextProfile):
            return await build_software_context(
                self, principal, request, profile, deadline=deadline
            )
        if request.target is not None or request.goal is not None:
            # Target sets and goals belong to software-task profiles only (M09 D1).
            raise ContextError(400, "C1-CX-001", "unsupported_selector")
        if set(request.fields) - profile.fields.keys():
            raise ContextError(400, "C1-CX-001", "unknown_field")
        digest = _digest(
            {
                "request": request_digest(request),
                "context_profile": catalog.digest(request.profile, request.profile_version),
                "schemas": {
                    name: profile_digest(value)
                    for name, value in sorted(self.runtime.registry.profiles.items())
                },
            }
        )
        position = None
        if request.cursor:
            try:
                position = self.runtime.query.codec.decode(
                    request.cursor,
                    principal=principal.id,
                    filter_digest=digest,
                    order=ORDER,
                    revision=request.revision,
                )
                if not re.fullmatch(r"0|[1-9][0-9]{0,2}", position.last_key[0]):
                    raise CursorError("invalid context position")
                if not re.fullmatch(r"[0-9a-f]{64}", position.last_key[1]):
                    raise CursorError("invalid context prefix")
            except CursorError as exc:
                raise ContextError(409, "C1-CX-011", "restart_required") from exc
        revision = position.revision if position else request.revision
        if revision is None:
            # Independent reads share the original deadline. Neither result
            # reaches retrieval until both complete; failures await siblings.
            head_task = asyncio.create_task(self.runtime.knowledge.head())
            plan_task = asyncio.create_task(
                self.runtime.query.selection(principal, deadline=deadline)
            )
            try:
                await asyncio.gather(head_task, plan_task)
            except BaseException:
                for task in (head_task, plan_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(head_task, plan_task, return_exceptions=True)
                raise
            revision = head_task.result()
            plan, _ = plan_task.result()
        else:
            plan, _ = await self.runtime.query.selection(principal, deadline=deadline)
        records = await self.runtime.query.records(plan, revision, deadline=deadline)
        try:
            anchor = resolve_anchor(
                records, request.anchor, profile, registry=self.runtime.registry
            )
        except ContextError as exc:
            if position and exc.status == 404:
                raise ContextError(409, "C1-CX-011", "restart_required") from exc
            raise
        topics = resolve_topics(records, request.topics, profile)
        if anchor["outcome"] != "resolved" or topics["outcome"] != "resolved":
            if position:
                raise ContextError(409, "C1-CX-011", "restart_required")
            await self.runtime.query.planner.finalize(principal, plan, deadline=deadline)
            return {
                "outcome": anchor["outcome"]
                if anchor["outcome"] != "resolved"
                else topics["outcome"],
                "revision": revision,
                "anchor_resolution": {
                    key: value for key, value in anchor.items() if not key.startswith("_")
                },
                "topic_resolution": {
                    key: value for key, value in topics.items() if not key.startswith("_")
                },
            }
        selection = select_context(
            records,
            anchor["anchor"]["id"],
            topics["topics"],
            profile,
            request,
            deadline=deadline,
            registry=self.runtime.registry,
        )
        units = build_units(records, selection, profile, self.runtime.registry, deadline=deadline)
        common_dependencies = frozenset(
            anchor.get("_dependencies", [])
            + topics.get("_dependencies", [])
            + selection.get("_dependencies", [])
        )
        matching_dependencies = {
            item["node_id"]: item.get("_dependencies", []) for item in selection["matched"]
        }
        for unit in units:
            unit["_dependencies"] = sorted(
                set(unit.get("_dependencies", []))
                | set(matching_dependencies.get(unit["node_id"], []))
            )
        public_units = prepare_units(units)
        interpretation = {
            "profile": profile.name,
            "profile_version": profile.version,
            "profile_digest": catalog.digest(profile.name, profile.version),
            "revision": revision,
            "anchor": anchor["anchor"],
            "topics": topics["topics"],
            "narrowing": {
                "keywords_all": [term.model_dump(mode="json") for term in request.keywords_all],
                "keywords_any": [term.model_dump(mode="json") for term in request.keywords_any],
                "project_ref": request.project_ref,
            },
        }
        offset = int(position.last_key[0]) if position else 0
        if offset > len(units) or (
            position
            and position.last_key[1]
            != _checkpoint(
                units, public_units, offset, interpretation, records, plan, common_dependencies
            )
        ):
            raise ContextError(409, "C1-CX-011", "restart_required")

        def cursor_for_offset(end: int) -> str | None:
            if end >= len(units):
                return None
            return self.runtime.query.codec.encode(
                principal=principal.id,
                revision=revision,
                filter_digest=digest,
                order=ORDER,
                last_key=(
                    str(end),
                    _checkpoint(
                        units, public_units, end, interpretation, records, plan, common_dependencies
                    ),
                ),
            )

        base = {
            "interpretation": interpretation,
            "orientation": _orientation(selection, records),
            "fields": request.fields,
            "field_predicates": {
                name: value if isinstance(value, str) else value.model_dump(mode="json")
                for name, value in profile.fields.items()
            },
            "anchor_label": anchor["anchor"]["label"],
            "revision": revision,
        }
        page = build_page(
            base,
            public_units,
            offset=offset,
            maximum=request.budget.maximum,
            cursor_for_offset=cursor_for_offset,
            deadline=deadline,
        )
        if time.monotonic() >= deadline:
            raise ContextError(503, "C1-CX-014", "time_budget")
        await self.runtime.query.planner.finalize(principal, plan, deadline=deadline)
        response: dict[str, Any] = {
            "outcome": "resolved",
            "revision": revision,
            "bounds": page["bounds"],
        }
        for format in request.formats:
            response[format] = page[format]
        return response
