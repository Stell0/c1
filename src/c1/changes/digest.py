"""Canonical ChangeSet payload and receipt encoding.

The digest covers the proposal, not mutable workflow fields such as status,
validation, review, or the eventual knowledge commit.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Encode ordinary JSON values without whitespace or floating NaN values."""
    try:
        return json.dumps(
            _json_value(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be canonical JSON-compatible") from exc


def request_digest(
    base_revision: str,
    operations: Sequence[Any],
    rationale: str | None,
) -> str:
    """D3 SHA-256 digest of the exact normalized proposal payload."""
    payload = {
        "base_revision": base_revision,
        "operations": list(operations),
        "rationale": rationale,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def receipt_message(
    *,
    changeset_id: str,
    attempt: int,
    principal_id: str,
    repository: str,
    digest: str,
) -> str:
    """D3 knowledge commit message; all fields identify the approved attempt."""
    if attempt < 1:
        raise ValueError("attempt must be positive")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("digest must be a lowercase SHA-256 hex digest")
    if not all((changeset_id, principal_id, repository)):
        raise ValueError("receipt identifiers must be nonempty")
    return canonical_json(
        {
            "c1": 2,
            "changeset": changeset_id,
            "attempt": attempt,
            "principal": principal_id,
            "repository": repository,
            "digest": digest,
        }
    )
