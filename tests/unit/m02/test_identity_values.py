import re
import uuid

import pytest
from pydantic import ValidationError

from c1.model.diagnostics import Diagnostic, ProfileError, fail
from c1.model.ids import mint_id, validate_iri


def test_canonical_id_is_uuid4_and_kind_scoped() -> None:
    first = mint_id("entity")
    second = mint_id("entity")
    assert first != second
    assert first.startswith("urn:c1:instance:dev:entity/")
    assert uuid.UUID(first.rsplit("/", 1)[1]).version == 4
    assert re.fullmatch(r"urn:c1:instance:dev:entity/[0-9a-f-]{36}", first)
    assert mint_id("source", "https://example.org/c1/").startswith("https://example.org/c1/source/")


@pytest.mark.parametrize(
    "iri",
    ["/relative", "entity/one", "http://", "urn:c1:bad space", "urn:x%QQ"],
)
def test_invalid_iri_rejected(iri: str) -> None:
    with pytest.raises(ProfileError) as caught:
        validate_iri(iri)
    assert caught.value.diagnostics[0].code == "C1-IX-030"


@pytest.mark.parametrize("iri", ["javascript:alert(1)", "data:text/plain,hello", "file:///tmp/a"])
def test_absolute_iri_scheme_is_preserved_as_data(iri: str) -> None:
    assert validate_iri(iri) == iri


def test_diagnostic_is_stable_and_frozen() -> None:
    with pytest.raises(ProfileError) as caught:
        fail("C1-PR-001", "bad manifest", "/version")
    assert caught.value.diagnostics == [
        Diagnostic(code="C1-PR-001", severity="error", path="/version", message="bad manifest")
    ]
    with pytest.raises(ValidationError):
        caught.value.diagnostics[0].code = "changed"
