"""Bounded native OpenFGA operations against one configured store/model."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Self

import httpx

from c1 import roundtrips

Tuple = tuple[str, str, str]
_FRESH = "HIGHER_CONSISTENCY"
# Whole-store binding scans stop here and fail closed (M09a D4).
SCAN_MAX_PAGES = 2000


class FGAError(RuntimeError):
    pass


def resource_object(identifier: str) -> str:
    return "resource:" + hashlib.sha256(identifier.encode()).hexdigest()


def scope_object(identifier: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier):
        raise ValueError("invalid scope identifier")
    return "scope:" + identifier


def read_relation_is_derivable(model: Any) -> bool:
    """True when `resource#can_read` is exactly `reader from bound_to` (M14a).

    Then `can_read(user, r)` holds if and only if some live `bound_to` scope of
    `r` has `user` as a `reader`; `scope#reader` must be directly assigned
    (users or group members) so that ListObjects over it is the same relation.
    Any other model shape disables derived read decisions.
    """
    if not isinstance(model, dict) or not isinstance(model.get("type_definitions"), list):
        return False
    types = {item.get("type"): item for item in model["type_definitions"] if isinstance(item, dict)}
    resource = (types.get("resource") or {}).get("relations") or {}
    scope = (types.get("scope") or {}).get("relations") or {}
    # The API serves camelCase keys; the packaged model file uses snake_case.
    can_read = _snake_keys(resource.get("can_read"))
    if not isinstance(can_read, dict) or set(can_read) != {"tuple_to_userset"}:
        return False
    tts = can_read["tuple_to_userset"]
    if not isinstance(tts, dict) or set(tts) != {"tupleset", "computed_userset"}:
        return False
    tupleset, computed = tts["tupleset"], tts["computed_userset"]
    if not isinstance(tupleset, dict) or not isinstance(computed, dict):
        return False
    if tupleset.get("relation") != "bound_to" or computed.get("relation") != "reader":
        return False
    if tupleset.get("object") or computed.get("object"):
        return False
    return bool(_snake_keys(scope.get("reader")) == {"this": {}})


def _snake_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            re.sub(r"(?<!^)(?=[A-Z])", "_", str(key)).lower(): _snake_keys(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_snake_keys(item) for item in value]
    return value


def model_definition() -> dict[str, Any]:
    packaged = Path(__file__).parent / "c1-v1.json"
    path = (
        packaged
        if packaged.is_file()
        else Path(__file__).resolve().parents[3] / "deployment/openfga/c1-v1.json"
    )
    value: dict[str, Any] = json.loads(path.read_text())
    return value


class FGA:
    def __init__(
        self,
        url: str,
        token: str,
        store_id: str = "",
        model_id: str = "",
        timeout: float = 5.0,
    ) -> None:
        self.store_id = store_id
        self.model_id = model_id
        # Set by `ready()`; derived read decisions require a verified model.
        self.read_model_verified = False
        # M14b D3: set by `verify_change_log()`; the finalize shortcut needs it.
        self.change_log_verified = False
        # M14b D2: binding-source inputs (performance only, never decisions).
        self.read_concurrency = 16
        self.last_scan_pages: int | None = None
        self._client = httpx.AsyncClient(
            base_url=url.rstrip("/"),
            timeout=timeout,
            trust_env=False,
            headers={"Authorization": "Bearer " + token},
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        with roundtrips.timed("openfga"):
            return await self._request_untimed(method, path, **kwargs)

    async def _request_untimed(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, **kwargs)
            if response.is_error:
                raise FGAError("authorization service rejected request")
            if not response.content:
                return {}
            payload = response.json()
            if not isinstance(payload, dict):
                raise FGAError("invalid authorization response")
            return payload
        except (httpx.HTTPError, ValueError):
            raise FGAError("authorization service unavailable") from None

    @property
    def _path(self) -> str:
        if not re.fullmatch(r"[A-Za-z0-9]+", self.store_id):
            raise FGAError("authorization store is not configured")
        return "/stores/" + self.store_id

    async def create_store(self, name: str) -> None:
        store = await self._request("POST", "/stores", json={"name": name})
        self.store_id = str(store["id"])
        model = await self._request(
            "POST", self._path + "/authorization-models", json=model_definition()
        )
        self.model_id = str(model["authorization_model_id"])

    async def delete_store(self) -> None:
        await self._request("DELETE", self._path)

    async def ready(self) -> bool:
        try:
            response = await self._request(
                "GET", self._path + "/authorization-models/" + self.model_id
            )
        except FGAError:
            return False
        # M14a (ADR-0025): readiness fails closed unless the deployed model has
        # the read shape that derived read decisions rely on.
        self.read_model_verified = read_relation_is_derivable(
            response.get("authorization_model", {})
        )
        return self.read_model_verified

    async def check(self, user: str, relation: str, object: str) -> bool:
        result = await self._request(
            "POST",
            self._path + "/check",
            json={
                "authorization_model_id": self.model_id,
                "consistency": _FRESH,
                "tuple_key": {"user": user, "relation": relation, "object": object},
            },
        )
        return result.get("allowed") is True

    async def list_objects(self, user: str, relation: str, type: str) -> list[str]:
        """Enumerate live objects; callers must reject the server's unmarked cap."""
        result = await self._request(
            "POST",
            self._path + "/list-objects",
            json={
                "authorization_model_id": self.model_id,
                "consistency": _FRESH,
                "user": user,
                "relation": relation,
                "type": type,
            },
        )
        objects = result.get("objects")
        if not isinstance(objects, list) or any(not isinstance(item, str) for item in objects):
            raise FGAError("invalid object enumeration response")
        return objects

    async def batch_check(self, checks: list[Tuple]) -> list[bool]:
        decisions: list[bool] = []
        for start in range(0, len(checks), 50):
            chunk = checks[start : start + 50]
            payload = await self._request(
                "POST",
                self._path + "/batch-check",
                json={
                    "authorization_model_id": self.model_id,
                    "consistency": _FRESH,
                    "checks": [
                        {
                            "correlation_id": str(i),
                            "tuple_key": {"user": u, "relation": r, "object": o},
                        }
                        for i, (u, r, o) in enumerate(chunk)
                    ],
                },
            )
            result = payload.get("result")
            if not isinstance(result, dict):
                raise FGAError("invalid batch authorization response")
            for i in range(len(chunk)):
                item = result.get(str(i))
                if (
                    not isinstance(item, dict)
                    or item.get("error")
                    or not isinstance(item.get("allowed"), bool)
                ):
                    raise FGAError("invalid batch authorization decision")
                decisions.append(item["allowed"] is True)
        return decisions

    async def read(self, *, user: str = "", relation: str = "", object: str = "") -> list[Tuple]:
        key = {k: v for k, v in {"user": user, "relation": relation, "object": object}.items() if v}
        result: list[Tuple] = []
        token = ""
        seen: set[str] = set()
        for _ in range(100):
            body = {
                "tuple_key": key,
                "page_size": 100,
                "consistency": _FRESH,
                "continuation_token": token,
            }
            payload = await self._request("POST", self._path + "/read", json=body)
            try:
                for item in payload.get("tuples", []):
                    k = item["key"]
                    result.append((str(k["user"]), str(k["relation"]), str(k["object"])))
            except (KeyError, TypeError):
                raise FGAError("invalid tuple response") from None
            token = payload.get("continuation_token", "")
            if not token:
                return result
            if token in seen:
                raise FGAError("authorization pagination did not advance")
            seen.add(token)
        raise FGAError("authorization tuple limit exceeded")

    async def bindings(self, resource: str) -> list[str]:
        return [u for u, _, _ in await self.read(relation="bound_to", object=resource)]

    async def read_changes(
        self, token: str, *, max_pages: int = SCAN_MAX_PAGES
    ) -> tuple[str, bool]:
        """Advance through the store's change log from `token` (M14b D3).

        Returns the tail continuation token and whether any tuple change exists
        after `token`. An empty `token` walks the whole log. Errors, a repeated
        continuation or too many pages raise; callers treat that as "changed".
        """
        changed = False
        seen: set[str] = set()
        for _ in range(max_pages):
            params: dict[str, Any] = {"page_size": 100}
            if token:
                params["continuation_token"] = token
            payload = await self._request("GET", self._path + "/changes", params=params)
            changes = payload.get("changes", [])
            following = payload.get("continuation_token", "")
            if not isinstance(changes, list) or not isinstance(following, str):
                raise FGAError("invalid change log response")
            if changes:
                changed = True
            if not changes:
                return following or token, changed
            if not following or following == token or following in seen:
                raise FGAError("change log pagination did not advance")
            seen.add(following)
            token = following
        raise FGAError("change log page limit exceeded")

    async def verify_change_log(self) -> bool:
        """Show that a committed write is in the change log at once (M14b D3).

        OpenFGA hides changes newer than its configured horizon from the log;
        the finalize shortcut is sound only with no horizon. Startup writes one
        probe tuple that grants nothing (a group no relation references), reads
        the log from the position before it, and removes it. Any error, or a
        log that does not show the write, leaves the shortcut disabled.
        """
        self.change_log_verified = False
        probe = ("user:c1-change-log-probe", "member", "group:c1-change-log-probe")
        try:
            token, _changed = await self.read_changes("")
            await self.write([probe])
            try:
                _tail, changed = await self.read_changes(token)
            finally:
                await self.write([], [probe])
        except Exception:
            return False
        self.change_log_verified = changed
        return changed

    async def scan_bindings(self, *, max_pages: int = SCAN_MAX_PAGES) -> dict[str, list[str]]:
        """Every live `bound_to` user per resource object, from one whole-store read.

        The pinned OpenFGA rejects filtered bulk reads, so this reads the store
        without a tuple key and keeps `bound_to` tuples on `resource` objects,
        including users from scopes C1 does not know. Any error, a repeated
        continuation, or more than `max_pages` pages raises; nothing partial
        is returned (M09a D4).
        """
        result: dict[str, list[str]] = {}
        token = ""
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            body: dict[str, Any] = {"page_size": 100, "consistency": _FRESH}
            if token:
                body["continuation_token"] = token
            payload = await self._request("POST", self._path + "/read", json=body)
            try:
                for item in payload.get("tuples", []):
                    key = item["key"]
                    if key["relation"] == "bound_to" and str(key["object"]).startswith("resource:"):
                        result.setdefault(str(key["object"]), []).append(str(key["user"]))
            except (KeyError, TypeError):
                raise FGAError("invalid tuple response") from None
            token = payload.get("continuation_token", "")
            if not token:
                # M14b D2: the measured store size (all tuple kinds) steers the
                # next binding-source choice; it never affects a decision.
                self.last_scan_pages = page
                return result
            if token in seen:
                raise FGAError("authorization pagination did not advance")
            seen.add(token)
        raise FGAError("authorization scan page limit exceeded")

    async def write(self, tuples: list[Tuple], deletes: list[Tuple] | None = None) -> None:
        if not tuples and not deletes:
            return
        if len(tuples) + len(deletes or []) > 100:
            raise FGAError("authorization mutation limit exceeded")
        body: dict[str, Any] = {"authorization_model_id": self.model_id}
        for name, entries in (("writes", tuples), ("deletes", deletes or [])):
            if entries:
                body[name] = {
                    "tuple_keys": [{"user": u, "relation": r, "object": o} for u, r, o in entries]
                }
        await self._request("POST", self._path + "/write", json=body)

    async def ensure_tuple(self, user: str, relation: str, object: str, *, grant: bool) -> None:
        existing = (user, relation, object) in await self.read(
            user=user, relation=relation, object=object
        )
        if existing != grant:
            entry = (user, relation, object)
            await self.write([entry] if grant else [], [] if grant else [entry])

    async def bind(self, resource: str, scope: str) -> None:
        current = await self.bindings(resource)
        await self.write(
            [(scope, "bound_to", resource)] if scope not in current else [],
            [(old, "bound_to", resource) for old in current if old != scope],
        )
