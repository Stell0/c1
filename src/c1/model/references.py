"""Declared links to independently authorized C1 content resources."""

from __future__ import annotations

from c1.model.profiles import ProfileRegistry
from c1.model.records import C1

TIME = "http://www.w3.org/2006/time#"
IDENTITY = "urn:c1:ns:identity#"

RESOURCE_REFS = frozenset(
    {
        C1 + "keyword",
        C1 + "validDuring",
        C1 + "evidence",
        C1 + "assertionRef",
        C1 + "candidate",
        C1 + "partOfDocument",
        "http://www.w3.org/2004/02/skos/core#inScheme",
        "http://www.w3.org/ns/oa#hasSource",
        "http://www.w3.org/ns/oa#hasSelector",
        "http://www.w3.org/ns/prov#wasGeneratedBy",
        "http://www.w3.org/ns/prov#used",
        C1 + "output",
        TIME + "hasBeginning",
        TIME + "hasEnd",
        IDENTITY + "from",
        IDENTITY + "to",
        IDENTITY + "resolution",
    }
)


def is_independent_reference(predicate: str, registry: ProfileRegistry) -> bool:
    """Organizational IRIs and principal IDs are not content-resource joins."""
    if predicate in RESOURCE_REFS:
        return True
    definition = registry.predicates.get(predicate)
    return definition is not None and any(kind in registry.classes for kind in definition.ranges)
