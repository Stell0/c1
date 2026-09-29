"""Check supported backend representation before approving a payload."""

from collections.abc import Sequence

from c1.changes.models import ChangeOperation, CreateOperation, ReplaceOperation
from c1.model.diagnostics import Diagnostic
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.storage.mapping import record_to_document
from c1.storage.terminus import StorageError


def storage_diagnostics(
    operations: Sequence[ChangeOperation], registry: ProfileRegistry, instance_base: str
) -> list[Diagnostic]:
    """Called only after semantic validation; no database or policy lookup."""
    diagnostics = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, (CreateOperation, ReplaceOperation)):
            continue
        try:
            record_to_document(NodeRecord.model_validate(operation.record), registry, instance_base)
        except StorageError as exc:
            if exc.code != "C1-ST-004":
                raise
            diagnostics.append(
                Diagnostic(
                    code="C1-ST-004",
                    severity="error",
                    path=f"/operations/{index}/record/id",
                    message="Canonical ID is unsupported by the pinned storage profile",
                )
            )
    return diagnostics
