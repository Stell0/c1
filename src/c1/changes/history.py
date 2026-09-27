"""Authorized historical reads and bounded, revision-bound history pages."""

from __future__ import annotations

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
from c1.storage.mapping import storage_id
from c1.storage.terminus import BackendError, StorageError, Terminus

_REVISION = re.compile(r"branch:[A-Za-z0-9_-]+\Z")
_COMMIT = re.compile(r"[A-Za-z0-9_-]+\Z")
_MAX_LIMIT = 100


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

    def _document_ids(self, resource_id: str) -> list[str]:
        validate_iri(resource_id)
        ids: list[str] = []
        for definition in self.registry.classes.values():
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
    ) -> dict[str, Any] | None:
        """Return a page or ``None`` when current authority does not permit it.

        A cursor fixes the knowledge head and offset, but never confers access.
        Authorization runs before selection and again before data is returned.
        """
        before = await self.journal.head()
        if not (await self.plane.check_read(principal, resource_id)).allowed:
            return None
        if type(limit) is not int or not 1 <= limit <= _MAX_LIMIT:
            raise ValueError("history limit must be between 1 and 100")
        head = await self.knowledge.head()
        if cursor is None:
            offset = 0
        else:
            revision, offset = decode_cursor(cursor)
            if revision != head:
                raise StaleHistoryCursor("history cursor knowledge revision is stale")
        raw_entries: list[dict[str, Any]] = []
        document_ids = self._document_ids(resource_id)
        nonempty_histories = 0
        for document_id in document_ids:
            try:
                document_history = await self.knowledge.history(document_id)
                nonempty_histories += bool(document_history)
                raw_entries.extend(document_history)
            except BackendError as exc:
                if exc.status_code != 404:
                    raise
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
        if not (await self.plane.check_read(principal, resource_id)).allowed:
            return None
        if before != await self.journal.head() or head != await self.knowledge.head():
            return None
        return {
            "resource_id": resource_id,
            "revision": head,
            "items": page,
            "next_cursor": encode_cursor(head, next_offset) if next_offset < len(ordered) else None,
        }
