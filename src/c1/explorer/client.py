"""The Explorer's only route to C1: the public API, called in-process (M12 D1).

Requests pass through the API's own boundary middleware, routes,
validation, authorization and audit exactly as an external client's do.
The bearer token is the signed-in person's own access token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from starlette.types import ASGIApp


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: Any
    code: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def path_id(identifier: str) -> str:
    """Percent-encode a canonical IRI as one path segment."""
    return quote(identifier, safe="")


class ApiClient:
    def __init__(self, app: ASGIApp) -> None:
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://c1-api.internal",
            timeout=None,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def call(
        self,
        token: str,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: Any = None,
        idempotency_key: str | None = None,
    ) -> ApiResponse:
        if not path.startswith("/v1/"):
            raise ValueError("the Explorer calls only the public /v1 API")
        headers = {"Authorization": "Bearer " + token}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        response = await self._client.request(
            method, path, params=params or None, json=json, headers=headers
        )
        try:
            body: Any = response.json() if response.content else None
        except ValueError:
            body = None
        code = body.get("code", "") if isinstance(body, dict) else ""
        return ApiResponse(response.status_code, body, str(code) if code else "")


class ApiFailure(Exception):
    """A required API read failed; the page shows the API's refusal unchanged."""

    def __init__(self, response: ApiResponse) -> None:
        super().__init__(response.status)
        self.response = response
