"""Document reads built entirely from the current authorized selection."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import TYPE_CHECKING, Any

from c1.authorization.principal import Principal
from c1.documents.render import render_document
from c1.documents.search import part_matches, search_document
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import C1
from c1.query.cursor import CursorError
from c1.query.export import export_authorized
from c1.query.plan import AuthorizedPlan, QueryPlanError
from c1.query.service import AuthorizedRecords

if TYPE_CHECKING:
    from c1.runtime import Runtime

DC = "http://purl.org/dc/terms/"
MAX_PARTS = 2000


def _text(node: NodeRecord, predicate: str) -> str | None:
    return next(
        (
            item.lexical
            for item in node.properties.get(predicate, ())
            if isinstance(item, LiteralValue)
        ),
        None,
    )


def _iri(node: NodeRecord, predicate: str) -> str | None:
    return next(
        (item for item in node.properties.get(predicate, ()) if isinstance(item, str)), None
    )


def _part_payload(node: NodeRecord) -> dict[str, Any]:
    body = _text(node, C1 + "text") or ""
    return {
        "part_id": node.id,
        "title": _text(node, DC + "title"),
        "kind": _text(node, C1 + "partKind") or "text",
        "order_key": _text(node, C1 + "orderKey"),
        "text": body,
        "text_digest": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "text_length": len(body),
    }


def _parts(
    records: AuthorizedRecords, document_id: str, *, reconstruction: bool = False
) -> list[NodeRecord]:
    selected = [
        node
        for node in records.values()
        if C1 + "DocumentPart" in node.types and _iri(node, C1 + "partOfDocument") == document_id
    ]
    selected.sort(key=lambda node: (_text(node, C1 + "orderKey") or "", node.id))
    if reconstruction and len(selected) > MAX_PARTS:
        raise QueryPlanError(422, "C1-DC-006", "document_too_large")
    return selected


def _history_candidates(
    identifier: str,
    plan: AuthorizedPlan,
    records: AuthorizedRecords,
    journal: dict[str, list[dict[str, Any]]],
) -> tuple[set[str], dict[str, frozenset[str]]]:
    """Find readable past members and complete storage-class hints.

    Journal manifests identify candidates/classes, never history entries.
    Legacy IDs without a tracked creation retain all-class backend probes.
    """
    readable = frozenset(plan.authorized_ids)
    candidates = {part.id for part in _parts(records, identifier)}
    types = {key: set(node.types) for key, node in records.items()}
    origins: set[str] = set()
    proposals = {
        item["id"]: item
        for item in journal["ChangeSet"]
        if item.get("state") == "applied" and isinstance(item.get("id"), str)
    }
    for operation in journal["Operation"]:
        if operation.get("state") != "applied":
            continue
        payload = operation.get("payload", {})
        kind = operation.get("kind")
        if kind == "changeset_apply":
            raw_records = payload.get("records", ())
            proposal = proposals.get(operation.get("target"), {})
            created = {
                item["record"]["id"]
                for item in proposal.get("operations", ())
                if item.get("kind") == "create"
            }
        elif kind in {"provision", "probe_revision"}:
            raw_records = [payload.get("record")]
            created = {operation.get("target")} if kind == "provision" else set()
        else:
            continue
        for raw in raw_records:
            # No hidden record participates even in candidate/type selection.
            if not isinstance(raw, dict) or raw.get("id") not in readable:
                continue
            node = NodeRecord.model_validate(raw)
            types.setdefault(node.id, set()).update(node.types)
            if node.id in created:
                origins.add(node.id)
            if (
                C1 + "DocumentPart" in node.types
                and _iri(node, C1 + "partOfDocument") == identifier
            ):
                candidates.add(node.id)
    return candidates, {key: frozenset(types[key]) for key in origins}


async def _gather_bounded(work: list[Any]) -> list[Any]:
    """Cancel and await every sibling on failure, including deadline expiry."""
    tasks = [asyncio.create_task(item) for item in work]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def _digest(*parts: str | None) -> str:
    raw = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


class DocumentsService:
    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    async def _selection(
        self, principal: Principal, revision: str | None
    ) -> tuple[AuthorizedPlan, AuthorizedRecords, str, float]:
        deadline = time.monotonic() + self.runtime.settings.query_time_budget_ms / 1000
        if revision is None:
            selected_revision, selected = await _gather_bounded(
                [
                    self.runtime.knowledge.head(),
                    self.runtime.query.selection(principal, deadline=deadline),
                ]
            )
            plan, _ = selected
        else:
            selected_revision = revision
            plan, _ = await self.runtime.query.selection(principal, deadline=deadline)
        records = await self.runtime.query.records(plan, selected_revision, deadline=deadline)
        return plan, records, selected_revision, deadline

    async def _finish(self, principal: Principal, plan: AuthorizedPlan, deadline: float) -> None:
        await self.runtime.query.planner.finalize(principal, plan, deadline=deadline)

    async def _history_manifest(self) -> tuple[str, dict[str, list[dict[str, Any]]]]:
        before = await self.runtime.journal.head()
        manifest = await self.runtime.journal.list_many({"ChangeSet", "Operation"})
        if await self.runtime.journal.head() != before:
            raise QueryPlanError(409, "C1-DC-014", "restart_required")
        return before, manifest

    @staticmethod
    def _document(records: AuthorizedRecords, identifier: str) -> NodeRecord:
        document = records.get(identifier)
        if document is None or C1 + "Document" not in document.types:
            raise QueryPlanError(404, "C1-DC-404", "not_found")
        return document

    def _cursor(
        self,
        principal: Principal,
        revision: str | None,
        cursor: str | None,
        digest: str,
        order: str,
    ) -> tuple[str | None, tuple[str, str] | None]:
        if not cursor:
            return revision, None
        try:
            position = self.runtime.query.codec.decode(
                cursor,
                principal=principal.id,
                revision=revision,
                filter_digest=digest,
                order=order,
            )
        except CursorError as exc:
            raise QueryPlanError(400, "C1-DC-007", "invalid_cursor") from exc
        return position.revision, position.last_key

    def _next(
        self,
        principal: Principal,
        revision: str,
        digest: str,
        order: str,
        key: tuple[str, str],
    ) -> str:
        return self.runtime.query.codec.encode(
            principal=principal.id,
            revision=revision,
            filter_digest=digest,
            order=order,
            last_key=key,
        )

    async def list(
        self,
        principal: Principal,
        *,
        revision: str | None = None,
        title: str | None = None,
        text_contains: str | None = None,
        kind: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise QueryPlanError(422, "C1-DC-008", "invalid_limit")
        if title == "" or text_contains == "" or kind == "":
            raise QueryPlanError(400, "C1-DC-013", "invalid_filter")
        digest = _digest("documents", title, text_contains, kind)
        revision, after = self._cursor(principal, revision, cursor, digest, "id")
        plan, records, selected_revision, deadline = await self._selection(principal, revision)
        selected: list[tuple[NodeRecord, dict[str, Any]]] = []
        for node in records.values():
            if C1 + "Document" not in node.types:
                continue
            readable_parts = _parts(records, node.id)
            if kind is not None and not any(
                _text(part, C1 + "partKind") == kind for part in readable_parts
            ):
                continue
            result = search_document(node, readable_parts, title=title, text_contains=text_contains)
            if result is not None:
                selected.append((node, result))
        selected.sort(key=lambda item: item[0].id)
        count = len(selected)
        if after:
            selected = [item for item in selected if (item[0].id, item[0].id) > after]
        page = selected[:limit]
        next_cursor = (
            self._next(principal, selected_revision, digest, "id", (page[-1][0].id,) * 2)
            if page and len(selected) > limit
            else None
        )
        response = {
            "instance": self.runtime.settings.instance_id,
            "revision": selected_revision,
            "count": count,
            "items": [{"document": node.model_dump(mode="json"), **match} for node, match in page],
            "next_cursor": next_cursor,
        }
        await self._finish(principal, plan, deadline)
        return response

    async def detail(
        self, principal: Principal, identifier: str, *, revision: str | None = None
    ) -> dict[str, Any]:
        plan, records, selected_revision, deadline = await self._selection(principal, revision)
        document = self._document(records, identifier)
        result = {
            "document": document.model_dump(mode="json"),
            "parts": [
                _part_payload(part) for part in _parts(records, identifier, reconstruction=True)
            ],
            "revision": selected_revision,
        }
        await self._finish(principal, plan, deadline)
        return result

    async def parts(
        self,
        principal: Principal,
        identifier: str,
        *,
        revision: str | None = None,
        text_contains: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 200:
            raise QueryPlanError(422, "C1-DC-008", "invalid_limit")
        if text_contains == "":
            raise QueryPlanError(400, "C1-DC-013", "invalid_filter")
        digest = _digest("parts", identifier, text_contains)
        revision, after = self._cursor(principal, revision, cursor, digest, "part")
        plan, records, selected_revision, deadline = await self._selection(principal, revision)
        self._document(records, identifier)
        selected = [
            node
            for node in _parts(records, identifier)
            if text_contains is None or part_matches(node, text_contains)
        ]
        count = len(selected)
        if after:
            selected = [
                node for node in selected if (_text(node, C1 + "orderKey") or "", node.id) > after
            ]
        page = selected[:limit]
        next_cursor = (
            self._next(
                principal,
                selected_revision,
                digest,
                "part",
                (_text(page[-1], C1 + "orderKey") or "", page[-1].id),
            )
            if page and len(selected) > limit
            else None
        )
        result = {
            "instance": self.runtime.settings.instance_id,
            "revision": selected_revision,
            "count": count,
            "items": [_part_payload(part) for part in page],
            "next_cursor": next_cursor,
        }
        await self._finish(principal, plan, deadline)
        return result

    async def render(
        self,
        principal: Principal,
        identifier: str,
        *,
        revision: str | None = None,
        format: str = "markdown",
    ) -> dict[str, Any]:
        if format not in {"markdown", "text"}:
            raise QueryPlanError(400, "C1-DC-015", "invalid_format")
        plan, records, selected_revision, deadline = await self._selection(principal, revision)
        self._document(records, identifier)
        content = render_document(_parts(records, identifier, reconstruction=True), format=format)  # type: ignore[arg-type]
        result = {
            "instance": self.runtime.settings.instance_id,
            "revision": selected_revision,
            "format": format,
            "content": content,
        }
        await self._finish(principal, plan, deadline)
        return result

    async def export(
        self,
        principal: Principal,
        identifier: str,
        *,
        revision: str | None = None,
        format: str = "jsonld",
    ) -> dict[str, Any]:
        if format not in {"jsonld", "text"}:
            raise QueryPlanError(400, "C1-DC-015", "invalid_format")
        plan, records, selected_revision, deadline = await self._selection(principal, revision)
        document = self._document(records, identifier)
        parts = _parts(records, identifier, reconstruction=True)
        result: dict[str, Any] = {
            "instance": self.runtime.settings.instance_id,
            "revision": selected_revision,
            "format": format,
        }
        if format == "text":
            result["content"] = render_document(parts, format="text")
        else:
            result["snapshot"] = export_authorized(
                [document, *parts],
                self.runtime.registry,
                authorized_ids=frozenset(records),
            )
        await self._finish(principal, plan, deadline)
        return result

    async def history(
        self,
        principal: Principal,
        identifier: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise QueryPlanError(422, "C1-DC-008", "invalid_limit")
        digest = _digest("document-history", identifier)
        cursor_revision, after = self._cursor(principal, None, cursor, digest, "history")
        deadline = time.monotonic() + self.runtime.settings.query_time_budget_ms / 1000
        async with asyncio.timeout_at(deadline):
            selected, manifest = await _gather_bounded(
                [
                    self._selection(principal, None),
                    self._history_manifest(),
                ]
            )
            plan, records, selected_revision, _ = selected
            manifest_head, journal = manifest
            if manifest_head != plan.workflow_head:
                raise QueryPlanError(409, "C1-DC-014", "restart_required")
            if cursor_revision is not None and cursor_revision != selected_revision:
                raise QueryPlanError(409, "C1-DC-014", "restart_required")
            self._document(records, identifier)
            candidate_ids, storage_types = _history_candidates(identifier, plan, records, journal)
            if len(candidate_ids) > MAX_PARTS:
                raise QueryPlanError(422, "C1-DC-006", "document_too_large")
            backend_gate = asyncio.Semaphore(8)

            async def resource_history(resource_id: str) -> list[dict[str, Any]]:
                token: str | None = None
                items: list[dict[str, Any]] = []
                while True:
                    response = await self.runtime.changes.history_service.metadata(
                        plan,
                        resource_id,
                        selected_revision,
                        limit=100,
                        cursor=token,
                        storage_types=storage_types.get(resource_id),
                        backend_gate=backend_gate,
                    )
                    if response is None:
                        raise QueryPlanError(503, "C1-DC-010", "history_unavailable")
                    items.extend(response["items"])
                    if len(items) > MAX_PARTS:
                        raise QueryPlanError(422, "C1-DC-006", "document_too_large")
                    token = response["next_cursor"]
                    if token is None:
                        return items

            resource_ids = [identifier, *sorted(candidate_ids)]
            histories = dict(
                zip(
                    resource_ids,
                    await _gather_bounded([resource_history(key) for key in resource_ids]),
                    strict=True,
                )
            )
            revisions = {
                item["revision"]
                for resource_id, items in histories.items()
                if resource_id != identifier
                for item in items
            }
            if len(revisions) > MAX_PARTS:
                raise QueryPlanError(422, "C1-DC-006", "document_too_large")
            # Only attachment fields on these already authorized IDs contribute
            # to history. Finalization still rechecks the original complete plan.
            reference_dependent_types = {
                C1 + "Assertion",
                C1 + "Evidence",
                C1 + "ResolutionRecord",
                "urn:c1:ns:identity#Redirect",
            }
            narrow_snapshot = all(
                key in storage_types and not (storage_types[key] & reference_dependent_types)
                for key in resource_ids
            )
            history_plan = (
                AuthorizedPlan(
                    plan.workflow_head, plan.readable_scopes, tuple(resource_ids), plan.scope_by_id
                )
                if narrow_snapshot
                else plan
            )
            snapshots = {selected_revision: records}
            missing_revisions = sorted(revisions - snapshots.keys())
            for batch_start in range(0, len(missing_revisions), 8):
                batch = missing_revisions[batch_start : batch_start + 8]
                values = await _gather_bounded(
                    [
                        self.runtime.query.records(
                            history_plan,
                            rev,
                            deadline=deadline,
                            backend_gate=backend_gate,
                            storage_types=storage_types,
                        )
                        for rev in batch
                    ]
                )
                snapshots.update(zip(batch, values, strict=True))
            entries = {item["revision"]: item for item in histories[identifier]}
            for resource_id in sorted(candidate_ids):
                items = histories[resource_id]
                if any(item["recorded_at"] is None for item in items):
                    raise QueryPlanError(503, "C1-DC-010", "history_unavailable")
                attached_before = False
                for item in sorted(
                    items, key=lambda value: (value["recorded_at"], value["revision"])
                ):
                    historical = snapshots[item["revision"]].get(resource_id)
                    attached_now = (
                        historical is not None
                        and _iri(historical, C1 + "partOfDocument") == identifier
                    )
                    if attached_before or attached_now:
                        entries[item["revision"]] = item
                    attached_before = attached_now
                if len(entries) > MAX_PARTS:
                    raise QueryPlanError(422, "C1-DC-006", "document_too_large")
        ordered = sorted(
            entries.values(),
            key=lambda item: (item["recorded_at"] or "", item["revision"]),
            reverse=True,
        )
        if after:
            ordered = [
                item for item in ordered if (item["recorded_at"] or "", item["revision"]) < after
            ]
        page = ordered[:limit]
        next_cursor = (
            self._next(
                principal,
                selected_revision,
                digest,
                "history",
                (page[-1]["recorded_at"] or "", page[-1]["revision"]),
            )
            if page and len(ordered) > limit
            else None
        )
        result = {
            "instance": self.runtime.settings.instance_id,
            "revision": selected_revision,
            "count": len(entries),
            "items": page,
            "next_cursor": next_cursor,
        }
        async with asyncio.timeout_at(deadline):
            if await self.runtime.knowledge.head() != selected_revision:
                raise QueryPlanError(409, "C1-DC-014", "restart_required")
            await self._finish(principal, plan, deadline)
        return result
