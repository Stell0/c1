"""Deterministic JSON-LD export of already validated canonical records."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from c1.interchange.jsonld import CORE_CONTEXT, validate_records
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry


def _encode(value: str | LiteralValue) -> dict[str, str]:
    if isinstance(value, str):
        return {"@id": value}
    encoded = {"@value": value.lexical}
    if value.language is not None:
        encoded["@language"] = value.language
    else:
        encoded["@type"] = value.datatype
    return encoded


def export_jsonld(
    records: Iterable[NodeRecord], registry: ProfileRegistry | None = None
) -> dict[str, Any]:
    """Export full IRIs under a bundled context; no remote context is emitted."""
    registry = registry or ProfileRegistry()
    if CORE_CONTEXT not in registry.contexts:
        raise ValueError("The bundled core context is required for export")
    graph: list[dict[str, Any]] = []
    validated = validate_records(records, registry)
    for record in sorted(validated.records, key=lambda item: item.id):
        node: dict[str, Any] = {"@id": record.id, "@type": sorted(record.types)}
        for predicate in sorted(record.properties):
            node[predicate] = [
                _encode(value)
                for value in sorted(
                    record.properties[predicate],
                    key=lambda item: (
                        0 if isinstance(item, str) else 1,
                        item if isinstance(item, str) else item.lexical,
                        "" if isinstance(item, str) else item.datatype,
                        "" if isinstance(item, str) else item.language or "",
                    ),
                )
            ]
        graph.append(node)
    return {"@context": CORE_CONTEXT, "@graph": graph}


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a bundled JSON-LD fixture canonically")
    parser.add_argument("--fixture", type=Path, required=True)
    arguments = parser.parse_args()
    from c1.interchange.jsonld import import_jsonld

    fixture = arguments.fixture
    source = fixture / "fixture.jsonld" if fixture.is_dir() else fixture
    payload = cast(dict[str, Any], json.loads(source.read_text(encoding="utf-8")))
    batch = import_jsonld(payload)
    print(json.dumps(export_jsonld(batch.records), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
