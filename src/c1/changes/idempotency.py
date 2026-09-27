"""Scoped request idempotency in the durable workflow journal.

The caller batches :func:`idempotency_entry` with its ChangeSet or receipt
using ``Journal.save_many`` and the same expected workflow head. This keeps
the request reservation and its result in one workflow commit.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from c1.authorization.journal import Journal

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class IdempotencyConflict(ValueError):
    """A scoped request key was already used for a different digest."""


def validate_request_key(value: str | None) -> str:
    """Accept only 1–128 printable ASCII characters, without normalization."""
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise ValueError("Idempotency-Key must contain 1–128 printable ASCII characters")
    if any(ord(char) < 0x20 or ord(char) > 0x7E for char in value):
        raise ValueError("Idempotency-Key must contain printable ASCII only")
    return value


def idempotency_address(principal_id: str, repository: str, key: str) -> str:
    """Unambiguous, bounded journal address for one principal and repository."""
    validate_request_key(key)
    if not principal_id or not repository:
        raise ValueError("principal and repository must be nonempty")
    scope = json.dumps([principal_id, repository, key], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()


def idempotency_entry(
    principal_id: str,
    repository: str,
    key: str,
    digest: str,
    changeset_id: str,
    response: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Build an entry to save atomically with the request result."""
    address = idempotency_address(principal_id, repository, key)
    if not _DIGEST.fullmatch(digest):
        raise ValueError("digest must be a lowercase SHA-256 hex digest")
    if not changeset_id or not isinstance(response, dict):
        raise ValueError("changeset_id and response are required")
    return (
        "Idempotency",
        address,
        {
            "principal_id": principal_id,
            "repository": repository,
            "key": key,
            "digest": digest,
            "changeset_id": changeset_id,
            "response": response,
        },
    )


async def lookup_idempotency(
    journal: Journal,
    principal_id: str,
    repository: str,
    key: str,
    digest: str,
) -> dict[str, Any] | None:
    """Return a replay response, reject a changed payload, or report no reservation.

    The caller must hold the repository writer gate and use workflow-head CAS
    on a new reservation. A journal lookup alone is not a concurrency lock.
    """
    address = idempotency_address(principal_id, repository, key)
    if not _DIGEST.fullmatch(digest):
        raise ValueError("digest must be a lowercase SHA-256 hex digest")
    stored = await journal.get("Idempotency", address)
    if stored is None:
        return None
    if (
        stored.get("principal_id") != principal_id
        or stored.get("repository") != repository
        or stored.get("key") != key
    ):
        raise RuntimeError("idempotency journal address does not match its scope")
    if stored.get("digest") != digest:
        raise IdempotencyConflict("idempotency_conflict")
    response = stored.get("response")
    if not isinstance(response, dict) or not isinstance(stored.get("changeset_id"), str):
        raise RuntimeError("idempotency journal entry is incomplete")
    return {**response, "replayed": True}
