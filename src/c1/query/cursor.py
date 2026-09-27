"""HMAC-bound, expiring keyset cursors. A cursor conveys no authorization."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import string
import time
from dataclasses import dataclass
from typing import Any


class CursorError(ValueError):
    """Malformed, changed-context, or expired cursor."""


@dataclass(frozen=True, slots=True)
class CursorPosition:
    revision: str
    filter_digest: str
    order: str
    last_key: tuple[str, str]
    exp: int


class CursorCodec:
    def __init__(self, secret: str | bytes, *, ttl_seconds: int = 900) -> None:
        key = secret.encode("utf-8") if isinstance(secret, str) else secret
        if len(key) < 32:
            raise ValueError("cursor secret must contain at least 32 bytes")
        if ttl_seconds < 1 or ttl_seconds > 900:
            raise ValueError("cursor TTL must be between 1 and 900 seconds")
        self._key = key
        self._ttl = ttl_seconds

    def encode(
        self,
        *,
        principal: str,
        revision: str,
        filter_digest: str,
        order: str,
        last_key: tuple[str, str],
        now: int | None = None,
    ) -> str:
        current = int(time.time()) if now is None else now
        payload = {
            "v": 1,
            "principal": principal,
            "revision": revision,
            "filter_digest": filter_digest,
            "order": order,
            "last_key": list(last_key),
            "exp": current + self._ttl,
        }
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        signature = hmac.new(self._key, raw, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(raw + signature).rstrip(b"=").decode("ascii")

    def decode(
        self,
        token: str,
        *,
        principal: str,
        filter_digest: str,
        order: str,
        revision: str | None = None,
        now: int | None = None,
    ) -> CursorPosition:
        try:
            if (
                len(token) > 8192
                or not token
                or any(c not in string.ascii_letters + string.digits + "-_" for c in token)
            ):
                raise ValueError("invalid encoding")
            blob = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            if len(blob) <= 32:
                raise ValueError("short cursor")
            raw, signature = blob[:-32], blob[-32:]
            expected = hmac.new(self._key, raw, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("bad signature")
            payload: Any = json.loads(raw)
            if not isinstance(payload, dict) or set(payload) != {
                "v",
                "principal",
                "revision",
                "filter_digest",
                "order",
                "last_key",
                "exp",
            }:
                raise ValueError("invalid payload")
            if payload["v"] != 1 or type(payload["exp"]) is not int:
                raise ValueError("invalid version or expiry")
            key = payload["last_key"]
            if (
                not isinstance(key, list)
                or len(key) != 2
                or not all(isinstance(v, str) for v in key)
            ):
                raise ValueError("invalid key")
            if (
                payload["principal"],
                payload["filter_digest"],
                payload["order"],
            ) != (principal, filter_digest, order):
                raise ValueError("context changed")
            if not isinstance(payload["revision"], str) or not payload["revision"]:
                raise ValueError("invalid revision")
            if revision is not None and payload["revision"] != revision:
                raise ValueError("context changed")
            current = int(time.time()) if now is None else now
            if payload["exp"] <= current:
                raise ValueError("expired")
            return CursorPosition(
                payload["revision"], filter_digest, order, (key[0], key[1]), payload["exp"]
            )
        except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CursorError("invalid or expired cursor") from exc
