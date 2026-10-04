"""Authorized historical reads and bounded, revision-bound history pages."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import re
from datetime import UTC, datetime
from typing import Any

from c1.authorization.journal import Journal
from c1.authorization.plane import AuthorizationPlane
from c1.authorization.principal import Principal
from c1.changes.digest import canonical_json
from c1.model.ids import validate_iri
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.query.plan import AuthorizedPlan
from c1.storage.mapping import storage_id
from c1.storage.terminus import BackendError, StorageError, Terminus

_REVISION = re.compile(r"branch:[A-Za-z0-9_-]+\Z")
_COMMIT = re.compile(r"[A-Za-z0-9_-]+\Z")
_MAX_LIMIT = 100
_HISTORY_CONCURRENCY = 8


class InvalidHistoryCursor(ValueError):
    """The supplied cursor is malformed or outside the supported bounds."""


class StaleHistoryCursor(ValueError):
    """The knowledge head changed since the cursor was issued."""


def encode_cursor(revision: str, offset: int) -> str:
    if not _REVISION.fullmatch(revision) or not 0 <= offset <= 10_000_000:
        raise InvalidHistoryCursor("invalid history cursor position")
    payload = json.dumps([revision, offset], separators=(",", ":")).encode("ascii")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> tuple[str, int]:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise InvalidHistoryCursor("invalid history cursor")
    try:
        payload = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        revision, offset = json.loads(payload)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise InvalidHistoryCursor("invalid history cursor") from exc
    if (
        not isinstance(revision, str)
        or not _REVISION.fullmatch(revision)
        or type(offset) is not int
        or not 0 <= offset <= 10_000_000
        or encode_cursor(revision, offset) != value
    ):
        raise InvalidHistoryCursor("invalid history cursor")
    return revision, offset


def _history_entry(raw: dict[str, Any]) -> dict[str, Any]:
    identifier = raw.get("identifier")
    if not isinstance(identifier, str) or not _COMMIT.fullmatch(identifier):
        raise StorageError("C1-ST-003", "backend returned an invalid history revision")
    recorded_at = raw.get("timestamp")
    if isinstance(recorded_at, (int, float)) and not isinstance(recorded_at, bool):
        try:
            if not math.isfinite(recorded_at):
                raise ValueError("non-finite timestamp")
            recorded_at = (
                datetime.fromtimestamp(recorded_at, tz=UTC)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            )
        except (OverflowError, OSError, ValueError) as exc:
            raise StorageError(
                "C1-ST-003", "backend returned an invalid history timestamp"
            ) from exc
    elif recorded_at is not None and not isinstance(recorded_at, str):
        raise StorageError("C1-ST-003", "backend returned an invalid history timestamp")
    changeset_id: str | None = None
    attempt: int | None = None
    message = raw.get("message")
    if isinstance(message, str):
        try:
            receipt = json.loads(message)
        except ValueError:
            receipt = None
        if isinstance(receipt, dict) and receipt.get("c1") == 2:
            candidate = receipt.get("changeset")
            candidate_attempt = receipt.get("attempt")
            if (
                isinstance(candidate, str)
                and candidate
                and type(candidate_attempt) is int
                and candidate_attempt > 0
            ):
                changeset_id = candidate
                attempt = candidate_attempt
    return {
        "revision": "branch:" + identifier,
        "recorded_at": recorded_at,
        "changeset_id": changeset_id,
        "attempt": attempt,
    }


class HistoryService:
    """Injectable service with no authorization cache or historical scope fallback."""

    def __init__(
        self,
        knowledge: Terminus,
        plane: AuthorizationPlane,
        journal: Journal,
        registry: ProfileRegistry,
    ) -> None:
        self.knowledge = knowledge
        self.plane = plane
        self.journal = journal
        self.registry = registry

    def _document_ids(
        self, resource_id: str, storage_types: frozenset[str] | None = None
    ) -> list[str]:
        validate_iri(resource_id)
        ids: list[str] = []
        # Only trusted, complete type hints may narrow probes. An empty or
        # unknown hint preserves the default coverage of every declared class.
        known_types = (
            storage_types
            if storage_types and storage_types <= self.registry.classes.keys()
            else None
        )
        for definition in self.registry.classes.values():
            if known_types is not None and definition.iri not in known_types:
                continue
            candidate = NodeRecord(id=resource_id, types=[definition.iri], properties={})
            try:
                identifier = storage_id(candidate, definition, self.knowledge.config.instance_base)
            except StorageError as exc:
                if exc.code == "C1-ST-004":
                    continue
                raise
            if identifier not in ids:
                ids.append(identifier)
        return ids

    async def read(
        self, principal: Principal, resource_id: str, revision: str | None = None
    ) -> NodeRecord | None:
        """Read old content only while its stable ID is readable under current policy."""
        before = await self.journal.head()
        if not (await self.plane.check_read(principal, resource_id)).allowed:
            return None
        record = await self.knowledge.get_record(resource_id, self.registry, commit=revision)
        if record is None or not (await self.plane.check_read(principal, resource_id)).allowed:
            return None
        if before != await self.journal.head():
            return None
        return record

    async def restore_matches(
        self,
        principal: Principal,
        resource_id: str,
        revision: str,
        proposed_record: NodeRecord | dict[str, Any],
    ) -> bool:
        """Verify a compensating record against authorized historical content.

        RDF property value lists have set semantics, so their ordering does not
        distinguish a restore. A missing or newly restricted old record fails.
        """
        historical = await self.read(principal, resource_id, revision)
        if historical is None:
            return False
        try:
            proposed = NodeRecord.model_validate(proposed_record)
        except ValueError:
            return False
        if proposed.id != resource_id or set(proposed.types) != set(historical.types):
            return False

        def terms(record: NodeRecord) -> dict[str, list[str]]:
            return {
                predicate: sorted(canonical_json(value) for value in values)
                for predicate, values in record.properties.items()
            }

        return terms(proposed) == terms(historical)

    async def list(
        self,
        principal: Principal,
        resource_id: str,
        *,
        limit: int = 25,
        cursor: str | None = None,
        storage_types: frozenset[str] | None = None,
        backend_gate: asyncio.Semaphore | None = None,
    ) -> dict[str, Any] | None:
        """Return a page or ``None`` when current authority does not permit it.

        A cursor fixes the knowledge head and offset, but never confers access.
        Authorization runs before selection and again before data is returned.
        Internal type hints narrow only storage probes; backend entries remain
        authoritative. A shared gate bounds probes across multiple resources.
        """
        before = await self.journal.head()
        if not (await self.plane.check_read(principal, resource_id)).allowed:
            return None
        if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
            raise ValueError("history limit must be between 1 and 100")
        head = await self.knowledge.head()
        result = await self._fetch_metadata(
            resource_id,
            head,
            limit=limit,
            cursor=cursor,
            storage_types=storage_types,
            backend_gate=backend_gate,
        )
        if not (await self.plane.check_read(principal, resource_id)).allowed:
            return None
        if before != await self.journal.head() or head != await self.knowledge.head():
            return None
        return result

    async def metadata(
        self,
        plan: AuthorizedPlan,
        resource_id: str,
        revision: str,
        *,
        limit: int = 100,
        cursor: str | None = None,
        storage_types: frozenset[str] | None = None,
        backend_gate: asyncio.Semaphore | None = None,
    ) -> dict[str, Any] | None:
        """Internal metadata retrieval within a fresh authorized selection.

        The caller must finalize this request's plan and verify the knowledge
        head before publishing these results. The plan is never a cursor grant.
        """
        if not plan.contains(resource_id):
            return None
        return await self._fetch_metadata(
            resource_id,
            revision,
            limit=limit,
            cursor=cursor,
            storage_types=storage_types,
            backend_gate=backend_gate,
        )

    async def _fetch_metadata(
        self,
        resource_id: str,
        revision: str,
        *,
        limit: int,
        cursor: str | None,
        storage_types: frozenset[str] | None,
        backend_gate: asyncio.Semaphore | None,
    ) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
            raise ValueError("history limit must be between 1 and 100")
        if not _REVISION.fullmatch(revision):
            raise InvalidHistoryCursor("invalid history revision")
        head = revision
        if cursor is None:
            offset = 0
        else:
            revision, offset = decode_cursor(cursor)
            if revision != head:
                raise StaleHistoryCursor("history cursor knowledge revision is stale")
        raw_entries: list[dict[str, Any]] = []
        document_ids = self._document_ids(resource_id, storage_types)
        nonempty_histories = 0

        async def fetch_history(document_id: str) -> list[dict[str, Any]]:
            try:
                if backend_gate is None:
                    return await self.knowledge.history(document_id)
                async with backend_gate:
                    return await self.knowledge.history(document_id)
            except BackendError as exc:
                if exc.status_code != 404:
                    raise
                return []

        async def exists(document_id: str) -> bool:
            try:
                if backend_gate is None:
                    return await self.knowledge.get(document_id) is not None
                async with backend_gate:
                    return await self.knowledge.get(document_id) is not None
            except BackendError as exc:
                if exc.status_code != 404:
                    raise
                return False

        # M13: instance documents are only inserted or replaced, never deleted,
        # so every storage document a resource ever occupied exists at head.
        # Cheap existence reads select the classes whose backend history is
        # probed; a history probe costs time proportional to the commit count.
        present: list[str] = []
        for batch_start in range(0, len(document_ids), _HISTORY_CONCURRENCY):
            batch = document_ids[batch_start : batch_start + _HISTORY_CONCURRENCY]
            found = await asyncio.gather(*(exists(item) for item in batch))
            present.extend(item for item, ok in zip(batch, found, strict=True) if ok)
        document_ids = present
        # A stable resource can have occupied more than one storage class.
        # Preserve that coverage without serializing every independent probe.
        for batch_start in range(0, len(document_ids), _HISTORY_CONCURRENCY):
            tasks = [
                asyncio.create_task(fetch_history(item))
                for item in document_ids[batch_start : batch_start + _HISTORY_CONCURRENCY]
            ]
            try:
                histories = await asyncio.gather(*tasks)
            except BaseException:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise
            nonempty_histories += sum(bool(rows) for rows in histories)
            for rows in histories:
                raw_entries.extend(rows)
        entries = [_history_entry(entry) for entry in raw_entries]
        # The same stable identity may have appeared under more than one class.
        # Sort and deduplicate by commit, preserving a deterministic page order.
        by_revision = {entry["revision"]: entry for entry in entries}
        ordered = list(by_revision.values())
        if nonempty_histories > 1:
            if any(entry["recorded_at"] is None for entry in ordered):
                raise StorageError("C1-ST-003", "backend history cannot be ordered")
            ordered.sort(key=lambda entry: entry["recorded_at"], reverse=True)
        page = ordered[offset : offset + limit]
        next_offset = offset + len(page)
        return {
            "resource_id": resource_id,
            "revision": head,
            "items": page,
            "next_cursor": encode_cursor(head, next_offset) if next_offset < len(ordered) else None,
        }
