"""Canonical C1 identifiers, deliberately independent of storage keys."""

import re
import uuid
from urllib.parse import urlsplit

from c1.model.diagnostics import fail

DEFAULT_INSTANCE_BASE = "urn:c1:instance:dev:"
KINDS = frozenset(
    {
        "entity",
        "assertion",
        "source",
        "evidence",
        "activity",
        "resolution",
        "document",
        "part",
        "changeset",
    }
)
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_BAD = re.compile(r"[\x00-\x20\x7f<>\"{}|\\^`]")
_BAD_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")


def validate_iri(iri: str) -> str:
    """Return an absolute IRI after excluding unsafe or ambiguous syntax."""

    if not isinstance(iri, str) or not _SCHEME.match(iri) or _BAD.search(iri):
        fail("C1-IX-030", "Expected a safe absolute IRI")
    if _BAD_PERCENT.search(iri):
        fail("C1-IX-030", "IRI contains an invalid percent escape")
    try:
        parsed = urlsplit(iri)
    except ValueError:
        fail("C1-IX-030", "IRI is malformed")
    if not parsed.scheme or (parsed.scheme in {"http", "https"} and not parsed.netloc):
        fail("C1-IX-030", "IRI must be absolute")
    return iri


def mint_id(kind: str, instance_base: str = DEFAULT_INSTANCE_BASE) -> str:
    if kind not in KINDS:
        fail("C1-IX-030", f"Unsupported canonical ID kind: {kind}")
    validate_iri(instance_base)
    if not instance_base.endswith((":", "/", "#")):
        fail("C1-IX-030", "Instance IRI base must end with ':', '/', or '#'")
    return f"{instance_base}{kind}/{uuid.uuid4()}"
