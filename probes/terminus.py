"""Small HTTP-only TerminusDB probe for M01; this is not a product client."""

from __future__ import annotations

import re
from typing import Any, Self

import httpx

_PROBE_DATABASE = re.compile(r"c1_m01_[a-z0-9_]+\Z")
_VERSION_HEADER = "TerminusDB-Data-Version"
_AUTHOR = "c1-m01-probe"


class BackendError(Exception):
    """An HTTP backend failure, without request credentials or raw response text."""

    def __init__(self, status_code: int, error: Any) -> None:
        self.status_code = status_code
        self.error = error
        super().__init__(f"TerminusDB HTTP {status_code}: {error!r}")


class Terminus:
    def __init__(self, url: str, password: str, database: str, organization: str = "admin") -> None:
        self.database = database
        self.organization = organization
        # M09a (owner decision): do not reuse a pooled connection idle for more
        # than one second, so a request never races the server's idle close.
        self._client = httpx.AsyncClient(
            base_url=url.rstrip("/"),
            auth=httpx.BasicAuth("admin", password),
            timeout=30.0,
            limits=httpx.Limits(keepalive_expiry=1.0),
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        await self._client.aclose()

    @property
    def _database_path(self) -> str:
        return f"{self.organization}/{self.database}"

    @property
    def _document_path(self) -> str:
        return f"/api/document/{self._database_path}"

    def _check_probe_database(self) -> None:
        if not _PROBE_DATABASE.fullmatch(self.database):
            raise ValueError("database create/drop is limited to c1_m01_* probe databases")

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = await self._client.request(method, path, **kwargs)
        if response.is_error:
            try:
                error: Any = response.json()
            except ValueError:
                error = {"message": "non-JSON backend error"}
            raise BackendError(response.status_code, error)
        return response

    @staticmethod
    def _head_from(response: httpx.Response) -> str:
        version = response.headers.get(_VERSION_HEADER, "")
        if not version.startswith("branch:") or len(version) <= len("branch:"):
            raise ValueError("TerminusDB response lacks a branch data version")
        return str(version)

    @staticmethod
    def _expected_headers(expected_head: str | None) -> dict[str, str]:
        if expected_head is None:
            return {}
        if not expected_head.startswith("branch:") or len(expected_head) <= len("branch:"):
            raise ValueError("expected_head must be a full branch:<commit> token")
        return {_VERSION_HEADER: expected_head}

    async def create(self, schema: list[dict[str, Any]] | None = None) -> None:
        self._check_probe_database()
        # TerminusDB POST /api/db rejects an existing database; never silently reuse it.
        await self._request("POST", f"/api/db/{self._database_path}", json={"label": self.database})
        if schema is not None:
            await self.schema(schema)

    async def drop(self) -> None:
        self._check_probe_database()
        await self._request("DELETE", f"/api/db/{self._database_path}")

    async def schema(
        self,
        documents: list[dict[str, Any]],
        message: str = "M01 probe schema",
        expected_head: str | None = None,
    ) -> str:
        return await self.insert(documents, message, expected_head, graph_type="schema")

    async def head(self) -> str:
        response = await self._request(
            "GET", self._document_path, params={"as_list": "true", "count": 0}
        )
        return self._head_from(response)

    async def insert(
        self,
        docs: list[dict[str, Any]],
        message: str,
        expected_head: str | None = None,
        graph_type: str = "instance",
    ) -> str:
        response = await self._request(
            "POST",
            self._document_path,
            params={"graph_type": graph_type, "author": _AUTHOR, "message": message},
            headers=self._expected_headers(expected_head),
            json=docs,
        )
        return self._head_from(response)

    async def replace(
        self,
        docs: list[dict[str, Any]],
        message: str,
        expected_head: str | None = None,
        graph_type: str = "instance",
    ) -> str:
        response = await self._request(
            "PUT",
            self._document_path,
            params={"graph_type": graph_type, "author": _AUTHOR, "message": message},
            headers=self._expected_headers(expected_head),
            json=docs,
        )
        return self._head_from(response)

    async def delete_documents(
        self, ids: list[str], message: str, expected_head: str | None = None
    ) -> str:
        response = await self._request(
            "DELETE",
            self._document_path,
            params={"graph_type": "instance", "author": _AUTHOR, "message": message},
            headers=self._expected_headers(expected_head),
            json=ids,
        )
        return self._head_from(response)

    async def get(self, id: str, commit: str | None = None) -> dict[str, Any] | None:
        path = self._document_path
        if commit is not None:
            commit_id = commit.removeprefix("branch:").removeprefix("commit:")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", commit_id):
                raise ValueError("commit must be an identifier or branch:<identifier>")
            path += f"/local/commit/{commit_id}"
        # v12.0.7's streaming single-ID response embeds a 404 status line in
        # an HTTP 200 body for a missing document. as_list returns valid JSON [].
        response = await self._request("GET", path, params={"id": id, "as_list": "true"})
        result = response.json()
        if not isinstance(result, list) or len(result) > 1:
            raise ValueError("TerminusDB single-document response was not an array of up to one")
        if not result:
            return None
        if not isinstance(result[0], dict):
            raise ValueError("TerminusDB document response was not an object")
        return result[0]

    async def documents(self, commit: str | None = None) -> list[dict[str, Any]]:
        path = self._document_path
        if commit is not None:
            commit_id = commit.removeprefix("branch:").removeprefix("commit:")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", commit_id):
                raise ValueError("commit must be an identifier or branch:<identifier>")
            path += f"/local/commit/{commit_id}"
        response = await self._request("GET", path, params={"as_list": "true"})
        result = response.json()
        if not isinstance(result, list) or not all(isinstance(doc, dict) for doc in result):
            raise ValueError("TerminusDB document list response was not an array of objects")
        return result

    async def log(self) -> list[dict[str, Any]]:
        response = await self._request("GET", f"/api/log/{self._database_path}")
        result = response.json()
        if not isinstance(result, list):
            raise ValueError("TerminusDB log response was not an array")
        return result

    async def history(self, id: str) -> list[dict[str, Any]]:
        response = await self._request(
            "GET", f"/api/history/{self._database_path}", params={"id": id}
        )
        result = response.json()
        if not isinstance(result, list):
            raise ValueError("TerminusDB history response was not an array")
        return result

    async def diff(self, before: str, after: str) -> Any:
        response = await self._request(
            "POST",
            f"/api/diff/{self._database_path}",
            json={"before_data_version": before, "after_data_version": after},
        )
        return response.json()
