"""Jinja rendering with autoescape always on and a closed widget vocabulary (M12 D5).

API data is only ever inserted as escaped text. Nothing here marks data as
safe HTML, converts Markdown, or builds a link to an address that is not an
Explorer route for a C1 resource.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from jinja2 import Environment, FileSystemLoader, StrictUndefined

PREFIXES = (
    ("urn:c1:ns:core#", "core:"),
    ("urn:c1:ns:software#", "sw:"),
    ("urn:c1:ns:identity#", "identity:"),
    ("urn:c1:ns:directory#", "directory:"),
    ("urn:c1:ns:topics#", "topics:"),
    ("http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdf:"),
    ("http://www.w3.org/2000/01/rdf-schema#", "rdfs:"),
    ("http://www.w3.org/2001/XMLSchema#", "xsd:"),
    ("http://www.w3.org/2004/02/skos/core#", "skos:"),
    ("http://purl.org/dc/terms/", "dcterms:"),
    ("http://www.w3.org/ns/prov#", "prov:"),
    ("http://www.w3.org/ns/oa#", "oa:"),
    ("http://www.w3.org/2006/time#", "time:"),
)

# Review, lifecycle and origin are separate dimensions; none means "true" (D5).
REVIEW_LABELS = {
    "reported": "reported (not reviewed)",
    "confirmed": "confirmed under review policy",
    "disputed": "disputed",
}

SKOS_PREF = "http://www.w3.org/2004/02/skos/core#prefLabel"
DC_TITLE = "http://purl.org/dc/terms/title"


def compact(iri: object) -> str:
    text = str(iri)
    for namespace, prefix in PREFIXES:
        if text.startswith(namespace) and len(text) > len(namespace):
            return prefix + text[len(namespace) :]
    return text


def query(path: str, **params: object) -> str:
    """An Explorer-relative URL; parameters are percent-encoded, never raw."""
    items = [(k, str(v)) for k, v in params.items() if v not in (None, "")]
    return path + ("?" + urlencode(items) if items else "")


def is_literal(value: object) -> bool:
    return isinstance(value, dict) and "lexical" in value and "datatype" in value


def label_of(record: object) -> str:
    """The first preferred label or title of a record, as plain text."""
    if not isinstance(record, dict):
        return ""
    properties = record.get("properties") or {}
    for predicate in (SKOS_PREF, DC_TITLE):
        for value in properties.get(predicate, []):
            if is_literal(value):
                return str(value["lexical"])
    return ""


class Renderer:
    def __init__(self, *, instance_base_hint: str = "urn:c1:") -> None:
        directory = Path(__file__).resolve().parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(str(directory)),
            autoescape=True,
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.instance_base_hint = instance_base_hint
        self.env.globals.update(
            compact=compact,
            query=query,
            is_literal=is_literal,
            label_of=label_of,
            review_label=lambda value: REVIEW_LABELS.get(str(value), str(value)),
            resource_href=self.resource_href,
        )

    def resource_href(self, iri: object) -> str | None:
        """Internal Explorer link for a C1 resource IRI; ``None`` for anything else."""
        text = str(iri)
        if not text.startswith(self.instance_base_hint) or any(c.isspace() for c in text):
            return None
        return query("/explorer/resource", id=text)

    def render(self, template: str, **context: Any) -> str:
        return self.env.get_template(template).render(**context)
