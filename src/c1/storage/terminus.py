"""Configured TerminusDB document API; database routing is fixed at construction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

import httpx

from c1.model.ids import validate_iri

if TYPE_CHECKING:
    from c1.model.nodes import NodeRecord, ValidatedBatch
    from c1.model.profiles import ProfileRegistry

_SAFE_PATH_PART = re.compile(r"[a-z][a-z0-9_-]*\Z")
_TEST_DATABASE = re.compile(r"c1_m0[23]_[a-z0-9_]+\Z")
_VERSION_HEADER = "TerminusDB-Data-Version"
_AUTHOR = "c1-model"


class StorageError(Exception):
    """A safe, stable storage diagnostic."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class BackendError(StorageError):
    """Backend failure with status and server error code, never a request body."""

    def __init__(self, status_code: int, backend_code: str | None = None) -> None:
        self.status_code = status_code
        self.backend_code = backend_code
        detail = f"TerminusDB HTTP {status_code}"
        if backend_code:
            detail += f" ({backend_code})"
        super().__init__("C1-ST-002", detail)


@dataclass(frozen=True, repr=False)
class StorageConfig:
    """Trusted deployment configuration, never values taken from a request."""

    url: str
    password: str
    organization: str
    database: str
    instance_base: str

    def __post_init__(self) -> None:
        for name, value in (("organization", self.organization), ("database", self.database)):
            if not _SAFE_PATH_PART.fullmatch(value):
                raise ValueError(f"{name} must be a safe TerminusDB path component")
        parsed = httpx.URL(self.url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.host
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("storage URL must be an HTTP(S) origin without credentials or a path")
        if not self.password:
            raise ValueError("storage password is required")
        validate_iri(self.instance_base)
        if not self.instance_base.endswith((":", "/", "#")):
            raise ValueError("instance_base must end with ':', '/', or '#'")


class Terminus:
    """Product storage client with a single configured organization and database."""

    def __init__(self, config: StorageConfig) -> None:
        if not isinstance(config, StorageConfig):
            raise TypeError("Terminus accepts only StorageConfig")
        self.config = config
        self._client = httpx.AsyncClient(
            base_url=config.url.rstrip("/"),
            auth=httpx.BasicAuth("admin", config.password),
            timeout=30.0,
            trust_env=False,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        await self._client.aclose()

    @property
    def _database_path(self) -> str:
        return f"{self.config.organization}/{self.config.database}"

    @property
    def _document_path(self) -> str:
        return f"/api/document/{self._database_path}"

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = await self._client.request(method, path, **kwargs)
        if response.is_error:
            backend_code: str | None = None
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    value = payload.get("api:error")
                    if isinstance(value, dict):
                        code = value.get("@type")
                        if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9:_-]+", code):
                            backend_code = code
            except ValueError:
                pass
            raise BackendError(response.status_code, backend_code)
        return response

    @staticmethod
    def _head_from(response: httpx.Response) -> str:
        value = response.headers.get(_VERSION_HEADER, "")
        if not value.startswith("branch:") or not re.fullmatch(r"branch:[A-Za-z0-9_-]+", value):
            raise StorageError("C1-ST-003", "backend response lacks a branch data version")
        return str(value)

    @staticmethod
    def _expected_headers(expected_head: str) -> dict[str, str]:
        if not re.fullmatch(r"branch:[A-Za-z0-9_-]+", expected_head):
            raise ValueError("expected_head must be a full branch data version")
        return {_VERSION_HEADER: expected_head}

    async def create(self) -> None:
        """Create only an isolated M02/M03 test database."""
        self._check_test_database()
        await self._request(
            "POST", f"/api/db/{self._database_path}", json={"label": self.config.database}
        )

    async def drop(self) -> None:
        """Drop only an isolated M02/M03 test database."""
        self._check_test_database()
        await self._request("DELETE", f"/api/db/{self._database_path}")

    def _check_test_database(self) -> None:
        if not _TEST_DATABASE.fullmatch(self.config.database):
            raise StorageError("C1-ST-007", "database create/drop is limited to M02/M03 tests")

    async def head(self) -> str:
        response = await self._request(
            "GET", self._document_path, params={"as_list": "true", "count": 0}
        )
        return self._head_from(response)

    async def documents(self, *, graph_type: str = "instance") -> list[dict[str, Any]]:
        if graph_type not in ("instance", "schema"):
            raise ValueError("graph_type must be instance or schema")
        response = await self._request(
            "GET", self._document_path, params={"as_list": "true", "graph_type": graph_type}
        )
        payload = response.json()
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise StorageError("C1-ST-003", "backend returned an invalid document list")
        return payload

    async def schema_documents(self) -> list[dict[str, Any]]:
        return await self.documents(graph_type="schema")

    async def get(self, document_id: str, commit: str | None = None) -> dict[str, Any] | None:
        path = self._document_path
        if commit is not None:
            commit_id = commit.removeprefix("branch:").removeprefix("commit:")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", commit_id):
                raise ValueError("commit must be an identifier or branch:<identifier>")
            path += f"/local/commit/{commit_id}"
        response = await self._request("GET", path, params={"id": document_id, "as_list": "true"})
        payload = response.json()
        if not isinstance(payload, list) or len(payload) > 1:
            raise StorageError("C1-ST-003", "backend returned an invalid single document")
        if not payload:
            return None
        if not isinstance(payload[0], dict):
            raise StorageError("C1-ST-003", "backend returned an invalid single document")
        return payload[0]

    async def get_record(
        self,
        canonical_iri: str,
        registry: ProfileRegistry,
        commit: str | None = None,
    ) -> NodeRecord | None:
        """Resolve one declared class at a revision under current schema authority.

        Authorization is performed by the caller against current bindings before
        this internal storage method. This method never grants access by itself.
        """
        from c1.model.nodes import NodeRecord as NodeType
        from c1.storage.mapping import document_to_record, storage_id
        from c1.storage.schema import assert_installed_profiles

        validate_iri(canonical_iri)
        await assert_installed_profiles(self, registry)
        found: NodeRecord | None = None
        for definition in registry.classes.values():
            candidate = NodeType(id=canonical_iri, types=[definition.iri], properties={})
            try:
                document_id = storage_id(candidate, definition, self.config.instance_base)
            except StorageError as exc:
                if exc.code == "C1-ST-004":
                    continue
                raise
            document = await self.get(document_id, commit=commit)
            if document is None:
                continue
            record = document_to_record(document, registry)
            if record.id != canonical_iri:
                raise StorageError(
                    "C1-ST-005", "stored document ID collides with canonical identity"
                )
            if found is not None:
                raise StorageError("C1-ST-005", "canonical identity resolves to multiple documents")
            found = record
        return found

    async def log(
        self, *, start: int | None = None, count: int | None = None
    ) -> list[dict[str, Any]]:
        """Read commits, optionally in bounded pages; no arguments preserve old callers."""
        if start is not None and (type(start) is not int or start < 0):
            raise ValueError("start must be a nonnegative integer")
        if count is not None and (type(count) is not int or not 1 <= count <= 100):
            raise ValueError("count must be an integer from 1 to 100")
        if start is not None and count is None:
            raise ValueError("count is required when start is supplied")
        params = {"start": start or 0, "count": count} if count is not None else None
        response = await self._request("GET", f"/api/log/{self._database_path}", params=params)
        payload = response.json()
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise StorageError("C1-ST-003", "backend returned an invalid log")
        return payload

    async def history(self, document_id: str) -> list[dict[str, Any]]:
        """Read per-document revisions; callers enforce current authorization first."""
        if not document_id:
            raise ValueError("document_id must not be empty")
        response = await self._request(
            "GET", f"/api/history/{self._database_path}", params={"id": document_id}
        )
        payload = response.json()
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise StorageError("C1-ST-003", "backend returned an invalid history")
        return payload

    async def _insert(
        self,
        documents: list[dict[str, Any]],
        *,
        expected_head: str,
        message: str,
        graph_type: str = "instance",
        full_replace: bool = False,
    ) -> str:
        if graph_type not in ("instance", "schema"):
            raise ValueError("graph_type must be instance or schema")
        if full_replace and graph_type != "schema":
            raise ValueError("full_replace is reserved for schema installation")
        response = await self._request(
            "POST",
            self._document_path,
            params={
                "graph_type": graph_type,
                "author": _AUTHOR,
                "message": message,
                **({"full_replace": "true"} if full_replace else {}),
            },
            headers=self._expected_headers(expected_head),
            json=documents,
        )
        return self._head_from(response)

    async def _put(
        self,
        documents: list[dict[str, Any]],
        *,
        expected_head: str,
        message: str,
        create: bool = False,
    ) -> str:
        response = await self._request(
            "PUT",
            self._document_path,
            params={
                "graph_type": "instance",
                "author": _AUTHOR,
                "message": message,
                **({"create": "true"} if create else {}),
            },
            headers=self._expected_headers(expected_head),
            json=documents,
        )
        return self._head_from(response)

    async def install_profile(self, registry: ProfileRegistry) -> str:
        from c1.storage.schema import install_core_profile

        return await install_core_profile(self, registry)

    async def add_profile(self, registry: ProfileRegistry, profile_name: str) -> str:
        from c1.storage.schema import install_additive_profile

        return await install_additive_profile(self, registry, profile_name)

    async def write_records(
        self,
        batch: ValidatedBatch,
        registry: ProfileRegistry,
        *,
        expected_head: str,
        message: str = "C1 model records",
    ) -> str:
        from c1.interchange.jsonld import validate_records
        from c1.model.nodes import ValidatedBatch as BatchType
        from c1.storage.mapping import records_to_documents, reject_reserved_id
        from c1.storage.schema import assert_installed_profiles

        if not isinstance(batch, BatchType):
            raise TypeError("write_records requires a ValidatedBatch")
        for record in batch.records:
            reject_reserved_id(record.id)
        # A frozen Pydantic model still contains mutable lists. Revalidate the
        # exact supplied records before any network mutation.
        checked = validate_records(batch.records, registry)
        documents = records_to_documents(checked.records, registry, self.config.instance_base)
        await assert_installed_profiles(self, registry)
        return await self._insert(documents, expected_head=expected_head, message=message)

    async def upsert_records(
        self, batch: ValidatedBatch, registry: ProfileRegistry, *, expected_head: str, message: str
    ) -> str:
        """Commit validated creates and replacements with one durable message receipt."""
        from c1.interchange.jsonld import validate_records
        from c1.model.nodes import ValidatedBatch as BatchType
        from c1.storage.mapping import records_to_documents, reject_reserved_id
        from c1.storage.schema import assert_installed_profiles

        if not isinstance(batch, BatchType):
            raise TypeError("upsert_records requires a ValidatedBatch")
        if not message:
            raise ValueError("message must carry a commit receipt")
        for record in batch.records:
            reject_reserved_id(record.id)
        checked = validate_records(batch.records, registry)
        documents = records_to_documents(checked.records, registry, self.config.instance_base)
        await assert_installed_profiles(self, registry)
        return await self._put(documents, expected_head=expected_head, message=message, create=True)

    async def read_records(
        self, registry: ProfileRegistry, *, include_metadata: bool = False
    ) -> list[NodeRecord]:
        from c1.storage.mapping import documents_to_records
        from c1.storage.schema import assert_installed_profiles

        await assert_installed_profiles(self, registry)
        return documents_to_records(
            await self.documents(),
            registry,
            self.config.instance_base,
            include_metadata=include_metadata,
        )

    async def replace_records(
        self,
        batch: ValidatedBatch,
        registry: ProfileRegistry,
        *,
        expected_head: str,
        message: str = "C1 probe record revision",
    ) -> str:
        """Trusted test/revision helper; no client-facing knowledge write path."""
        from c1.interchange.jsonld import validate_records
        from c1.model.nodes import ValidatedBatch as BatchType
        from c1.storage.mapping import records_to_documents, reject_reserved_id
        from c1.storage.schema import assert_installed_profiles

        if not isinstance(batch, BatchType):
            raise TypeError("replace_records requires a ValidatedBatch")
        for record in batch.records:
            reject_reserved_id(record.id)
        checked = validate_records(batch.records, registry)
        documents = records_to_documents(checked.records, registry, self.config.instance_base)
        await assert_installed_profiles(self, registry)
        return await self._put(documents, expected_head=expected_head, message=message)
