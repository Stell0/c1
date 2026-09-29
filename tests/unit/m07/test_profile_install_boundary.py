"""A profile installation receipt must describe exactly one installed profile."""

import pytest
from pydantic import BaseModel, ValidationError

from c1.api.routes.changesets import ChangeSetCreate, OperationsEdit
from c1.changes.models import ChangeSet


@pytest.mark.parametrize("model", [ChangeSetCreate, OperationsEdit, ChangeSet])
def test_multiple_profile_installs_cannot_claim_one_applied_receipt(model: type[BaseModel]) -> None:
    with pytest.raises(ValidationError, match="exactly one operation"):
        model.model_validate(
            {
                "base_revision": "branch:fixed",
                "operations": [
                    {"kind": "install_profile", "profile": name} for name in ["topics", "batteries"]
                ],
                "rationale": "Install two profiles",
                **(
                    {"id": "cs", "author": "actor", "created": "now", "updated": "now"}
                    if model is ChangeSet
                    else {}
                ),
            }
        )
