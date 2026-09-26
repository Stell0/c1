"""Isolated OpenFGA freshness probe using the M01 prototype model.

All identifiers passed to this module are full OpenFGA objects (``user:u``,
``scope:s``, ``resource:r``). This is deliberately not the M03 policy model.
"""

# The generated openfga-sdk 0.10.4 model constructors and context hooks are untyped.
# mypy: disable-error-code=no-untyped-call

from __future__ import annotations

from typing import Self

from openfga_sdk import (
    ClientConfiguration,
    CreateStoreRequest,
    Metadata,
    ObjectRelation,
    OpenFgaClient,
    ReadRequestTupleKey,
    RelationMetadata,
    RelationReference,
    TupleToUserset,
    TypeDefinition,
    Userset,
    WriteAuthorizationModelRequest,
)
from openfga_sdk.client.models import ClientCheckRequest, ClientTuple, ClientWriteRequest
from openfga_sdk.credentials import (
    CredentialConfiguration,
    Credentials,
)

Tuple = tuple[str, str, str]
_FRESH = {"consistency": "HIGHER_CONSISTENCY"}


class FGAError(RuntimeError):
    """An OpenFGA setup, read, or mutation operation failed."""


def _model() -> WriteAuthorizationModelRequest:
    """The SDK object corresponding to deployment/openfga/model.fga."""
    direct = Userset(this={})
    return WriteAuthorizationModelRequest(
        schema_version="1.1",
        type_definitions=[
            TypeDefinition(type="user"),
            TypeDefinition(
                type="group",
                relations={"member": direct},
                metadata=Metadata(
                    relations={
                        "member": RelationMetadata(
                            directly_related_user_types=[RelationReference(type="user")]
                        )
                    }
                ),
            ),
            TypeDefinition(
                type="scope",
                relations={"reader": direct},
                metadata=Metadata(
                    relations={
                        "reader": RelationMetadata(
                            directly_related_user_types=[
                                RelationReference(type="user"),
                                RelationReference(type="group", relation="member"),
                            ]
                        )
                    }
                ),
            ),
            TypeDefinition(
                type="resource",
                relations={
                    "bound_to": direct,
                    "reader": Userset(
                        tuple_to_userset=TupleToUserset(
                            tupleset=ObjectRelation(object="", relation="bound_to"),
                            computed_userset=ObjectRelation(object="", relation="reader"),
                        )
                    ),
                },
                metadata=Metadata(
                    relations={
                        "bound_to": RelationMetadata(
                            directly_related_user_types=[RelationReference(type="scope")]
                        )
                    }
                ),
            ),
        ],
    )


class FGA:
    def __init__(
        self,
        url: str,
        token: str,
        store_id: str | None = None,
        model_id: str | None = None,
    ) -> None:
        self.store_id = store_id
        self.model_id = model_id
        credentials = (
            Credentials(
                method="api_token",
                configuration=CredentialConfiguration(api_token=token),
            )
            if token
            else None
        )
        self._client = OpenFgaClient(
            ClientConfiguration(
                api_url=url,
                store_id=store_id,
                authorization_model_id=model_id,
                credentials=credentials,
                timeout_millisec=2000,
            )
        )

    async def __aenter__(self) -> Self:
        await self._client.__aenter__()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self._client.__aexit__(exc_type, exc, tb)

    async def create_store(self, name: str) -> None:
        try:
            store = await self._client.create_store(CreateStoreRequest(name=name))
            self.store_id = store.id
            self._client.set_store_id(store.id)
            model = await self._client.write_authorization_model(_model())
            self.model_id = model.authorization_model_id
            self._client.set_authorization_model_id(self.model_id)
        except Exception:
            raise FGAError("OpenFGA store/model creation failed") from None

    async def delete_store(self) -> None:
        if self.store_id is None:
            return
        try:
            await self._client.delete_store()
        except Exception:
            raise FGAError("OpenFGA store deletion failed") from None
        self.store_id = None
        self.model_id = None

    async def write(self, tuples: list[Tuple], deletes: list[Tuple] | None = None) -> None:
        if not tuples and not deletes:
            return
        try:
            await self._client.write(
                ClientWriteRequest(
                    writes=[ClientTuple(user=u, relation=r, object=o) for u, r, o in tuples]
                    or None,
                    deletes=[ClientTuple(user=u, relation=r, object=o) for u, r, o in deletes or []]
                    or None,
                )
            )
        except Exception:
            raise FGAError("OpenFGA tuple mutation failed") from None

    async def check(self, user: str, relation: str, object: str) -> bool:
        """Fail closed when OpenFGA cannot return an allow decision."""
        if not self.store_id or not self.model_id:
            return False
        try:
            result = await self._client.check(
                ClientCheckRequest(user=user, relation=relation, object=object),
                dict(_FRESH),
            )
            return result.allowed is True
        except Exception:
            return False

    async def bindings(self, resource: str) -> list[str]:
        """Read all current direct scope bindings, including paginated results."""
        if not self.store_id:
            raise FGAError("OpenFGA store is not configured")
        scopes: list[str] = []
        token: str | None = None
        try:
            while True:
                options: dict[str, int | str | dict[str, int | str]] = dict(_FRESH)
                if token:
                    options["continuation_token"] = token
                result = await self._client.read(
                    ReadRequestTupleKey(object=resource, relation="bound_to"), options
                )
                scopes.extend(item.key.user for item in result.tuples)
                next_token = result.continuation_token or None
                if not next_token:
                    return scopes
                if next_token == token:
                    raise FGAError("OpenFGA read pagination did not advance")
                token = next_token
        except Exception:
            raise FGAError("OpenFGA binding read failed") from None

    async def bind(self, resource: str, scope: str) -> None:
        """Replace current bindings with one scope in a single tuple transaction."""
        current = await self.bindings(resource)
        if current == [scope]:
            return
        await self.write(
            [(scope, "bound_to", resource)] if scope not in current else [],
            [(old, "bound_to", resource) for old in current if old != scope],
        )
