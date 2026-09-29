"""Readable, declared-scheme topic resolution; no keyword inference."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from c1.context.profiles import ContextProfile
from c1.context.request import IDSelector, LabelSelector
from c1.context.resolve import candidate, label_matches, lifecycle
from c1.model.nodes import NodeRecord
from c1.model.records import SKOS


def topic_records(
    records: Mapping[str, NodeRecord], profile: ContextProfile
) -> dict[str, NodeRecord]:
    # The scheme is itself an independently readable resource.
    if profile.topic_scheme not in records:
        return {}
    return {
        key: node
        for key, node in records.items()
        if SKOS + "Concept" in node.types
        and profile.topic_scheme in node.properties.get(SKOS + "inScheme", [])
        and lifecycle(node) not in {"retracted", "superseded"}
    }


def resolve_topics(
    records: Mapping[str, NodeRecord],
    selectors: Sequence[str | IDSelector | LabelSelector],
    profile: ContextProfile,
) -> dict[str, Any]:
    concepts = topic_records(records, profile)
    dependencies: set[str] = set()
    if selectors and profile.topic_scheme in records:
        dependencies.add(profile.topic_scheme)
    results: list[dict[str, Any]] = []
    resolved: dict[str, dict[str, Any]] = {}
    for selector in selectors:
        if isinstance(selector, str):
            selector = LabelSelector(label=selector)
        if isinstance(selector, IDSelector):
            node = concepts.get(selector.id)
            matches = [candidate(node)] if node is not None else []
        else:
            matches = [
                candidate(node)
                for _, node in sorted(concepts.items())
                if label_matches(node, selector)
            ]
        outcome = "resolved" if len(matches) == 1 else "ambiguous" if matches else "unresolved"
        dependencies.update(item["id"] for item in matches)
        result: dict[str, Any] = {
            "selector": selector.model_dump(exclude_none=True),
            "outcome": outcome,
        }
        if outcome == "resolved":
            result["topic"] = matches[0]
            resolved[matches[0]["id"]] = matches[0]
        else:
            result["candidates"] = matches
        results.append(result)
    outcome = (
        "ambiguous"
        if any(item["outcome"] == "ambiguous" for item in results)
        else "unresolved"
        if any(item["outcome"] == "unresolved" for item in results)
        else "resolved"
    )
    return {
        "outcome": outcome,
        "topics": [resolved[key] for key in sorted(resolved)],
        "selectors": results,
        "_dependencies": sorted(dependencies),
    }
