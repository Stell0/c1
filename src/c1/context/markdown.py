"""Inert Markdown from a structured, already authorized context package."""

from __future__ import annotations

import re
from typing import Any

from c1.changes.digest import canonical_json
from c1.documents.render import _fence, escape_markdown_text


def _safe(value: Any) -> str:
    text = value if isinstance(value, str) else canonical_json(value)
    # Metadata is inline prose; untrusted newlines cannot create document sections.
    return escape_markdown_text(text).replace("\r", " ").replace("\n", " ")


def _cursor(value: str) -> str:
    """Keep generated base64url token length invariant under Markdown rendering."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("generated context cursor must be unpadded base64url")
    return "`" + value + "`"


def _value(value: dict[str, Any]) -> str:
    if value.get("kind") == "literal":
        result = (
            _safe(value.get("lexical", "")) + " (datatype: " + _safe(value.get("datatype")) + ")"
        )
        if value.get("language") is not None:
            result += "; language: " + _safe(value["language"])
        return result
    return (
        _safe(value.get("label", value.get("id", "")))
        + " (id: "
        + _safe(value.get("id"))
        + "; types: "
        + _safe(value.get("types", []))
        + ")"
    )


def _claim(claim: dict[str, Any], *, qualifier: bool = False) -> list[str]:
    prefix = "  - Qualifier " if qualifier else "- "
    label = _safe(claim.get("predicate_label", claim.get("predicate", ""))) + ": "
    first = prefix + (label if qualifier else "") + _value(claim["value"])
    first += "; assertion: " + _safe(claim["assertion_id"])
    for key in (
        "review_state",
        "origin",
        "lifecycle",
        "valid_time",
        "confidence",
        "confidence_method",
        "attributed_to",
        "activity",
        "attribution_kind",
        "measurement_id",
        "measurement_link_assertion_id",
        "measurement_link",
        "measurement_status",
        "measurement_links",
        "incomplete",
    ):
        if key in claim:
            first += "; " + key.replace("_", " ") + ": " + _safe(claim[key])
    if claim.get("manual_statement"):
        first += "; manual statement by " + _safe(claim.get("attributed_to"))
    first += "".join(f"[^{citation['n']}]" for citation in claim.get("citations", []))
    lines = [first]
    for item in claim.get("qualifiers", []):
        lines.extend(_claim(item, qualifier=True))
    return lines


def render_markdown(package: dict[str, Any]) -> str:
    """Render fixed sections; no stored text becomes live markup or a link."""
    sections = ["# " + _safe(package["title"]), "## Interpretation"]
    sections.extend(
        "- " + _safe(key) + ": " + _safe(value) for key, value in package["interpretation"].items()
    )
    sections.append("## Orientation")
    for path in package["orientation"]:
        labels = path.get("labels")
        if labels is None and path.get("nodes"):
            labels = []
            for index, node in enumerate(path["nodes"]):
                if index:
                    edge = path["edges"][index - 1]
                    labels.append(edge.get("predicate_label", edge["predicate"]))
                labels.append(node["label"])
        if labels is not None:
            sections.append(
                "- " + " → ".join(_safe(label) for label in labels) + "; path: " + _safe(path)
            )
        else:
            sections.append("- " + _safe(path))
    sections.append("## Facts")
    previous = None
    for unit in package["facts"]:
        if unit["node_id"] != previous:
            sections.append(
                "### " + _safe(unit["node_label"]) + " (" + _safe(unit["node_id"]) + ")"
            )
            previous = unit["node_id"]
        sections.append(
            "#### " + _safe(unit["predicate_label"]) + " (" + _safe(unit["predicate"]) + ")"
        )
        sections.append(
            "Unit: "
            + _safe(unit["id"])
            + "; sources: "
            + _safe(unit.get("sources", 0))
            + "; imports: "
            + _safe(unit.get("imports", 0))
            + "; source versions: "
            + _safe(unit.get("source_versions", []))
        )
        sections.append("Comparison: " + _safe(unit.get("comparison")))
        if unit.get("roles"):
            sections.append("Roles: " + _safe(unit["roles"]))
        if unit.get("disagreement", {}).get("competing"):
            sections.append("Disagreement: " + _safe(unit["disagreement"]))
        for claim in unit["claims"]:
            sections.extend(_claim(claim))
    sections.append("## Text")
    for citation in package["text"]:
        sections.append(
            "Excerpt for unit "
            + _safe(citation["unit_id"])
            + f"[^{citation['n']}]"
            + "; truncated: "
            + _safe(citation.get("excerpt_truncated", False))
        )
        if str(citation.get("excerpt_kind", "text")).startswith("code"):
            sections.append(_fence(citation["excerpt"], "text excerpt"))
        else:
            sections.append(
                "\n".join(
                    "> " + escape_markdown_text(line) for line in citation["excerpt"].split("\n")
                )
            )
    sections.append("## Disagreements")
    sections.extend("- " + _safe(disagreement) for disagreement in package["disagreements"])
    sections.append("## Gaps")
    sections.extend("- " + _safe(gap["field"]) + ": " + gap["message"] for gap in package["gaps"])
    sections.append("## Sources")
    for citation in package["sources"]:
        metadata = {
            key: value
            for key, value in citation.items()
            if key not in {"n", "excerpt", "excerpt_kind", "excerpt_truncated"}
        }
        sections.append(
            f"[^{citation['n']}]: " + _safe(citation["source_title"]) + "; " + _safe(metadata)
        )
    sections.append("## Bounds")
    sections.extend(
        "- "
        + _safe(key)
        + ": "
        + (_cursor(value) if key == "next_cursor" and value is not None else _safe(value))
        for key, value in package["bounds"].items()
    )
    sections.append("Format parity digest: " + package["format_parity_digest"])
    return "\n\n".join(sections) + "\n"
