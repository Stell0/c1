"""An immutable projection of the security journal at one data version (M09a D1).

The view answers the same questions as reading individual journal documents
and scanning pending operations, but from one listing taken at one data
version. Decision functions compare its version with the journal head they
read, so a view never answers for a different security state. Views are not
kept beyond the journal's own version-keyed listing.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from c1.authorization.models import Binding, Operation, Scope

_SCOPE_KINDS = frozenset({"scope_create", "scope_retire", "membership"})


@dataclass(frozen=True)
class SecurityView:
    version: str
    bindings: Mapping[str, Binding]
    scopes: Mapping[str, Scope]
    # Pending operations indexed by every target and by affected scope.
    _pending_by_target: Mapping[str, tuple[str, ...]]
    _pending_by_scope: Mapping[str, tuple[str, ...]]
    _pending_instance_grant: bool

    @classmethod
    def build(
        cls, version: str, entries: Iterable[tuple[str, str, dict[str, Any]]]
    ) -> SecurityView:
        bindings: dict[str, Binding] = {}
        scopes: dict[str, Scope] = {}
        by_target: dict[str, list[str]] = defaultdict(list)
        by_scope: dict[str, list[str]] = defaultdict(list)
        instance_grant = False
        for kind, key, payload in entries:
            if kind == "Binding":
                bindings[key] = Binding.model_validate(payload)
            elif kind == "Scope":
                scopes[key] = Scope.model_validate(payload)
            elif kind == "Operation":
                operation = Operation.model_validate(payload)
                if operation.state != "pending":
                    continue
                for target in operation.targets:
                    by_target[target].append(operation.id)
                if operation.kind in _SCOPE_KINDS and operation.target:
                    by_scope[operation.target].append(operation.id)
                if operation.kind == "instance_grant":
                    instance_grant = True
        return cls(
            version,
            MappingProxyType(bindings),
            MappingProxyType(scopes),
            MappingProxyType({k: tuple(v) for k, v in by_target.items()}),
            MappingProxyType({k: tuple(v) for k, v in by_scope.items()}),
            instance_grant,
        )

    def binding(self, identifier: str) -> Binding | None:
        return self.bindings.get(identifier)

    def scope(self, identifier: str) -> Scope | None:
        return self.scopes.get(identifier)

    def pending(self, identifier: str = "", scope: str = "", *, excluding: str = "") -> bool:
        """Same answer as `Bindings.pending` over this version's operations."""
        targets = self._pending_by_target.get(identifier, ()) if identifier else ()
        if any(op != excluding for op in targets):
            return True
        return bool(scope) and any(op != excluding for op in self._pending_by_scope.get(scope, ()))

    @property
    def pending_instance_grant(self) -> bool:
        return self._pending_instance_grant
