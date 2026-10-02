"""Structured and inert Markdown renderings of one test-development selection.

Both formats are produced from the same authorized units. The goal changes
only section labels and the header statement, never which units appear.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from c1.changes.digest import canonical_json
from c1.context.markdown import _cursor, _safe
from c1.context.software import UNIT_SECTIONS
from c1.context.structured import parity_identifiers, public_value, unit_citations
from c1.documents.render import _fence, escape_markdown_text

GOAL_STATEMENTS = {
    "conformance": (
        "Goal: conformance. The normative expectations are the only oracle source; "
        "the implementation shows current behavior and may be defective."
    ),
    "characterization": (
        "Goal: characterization. The current implementation behavior is being "
        "characterized; normative expectations are shown for comparison."
    ),
}
SECTION_LABELS = {
    "conformance": {
        "normative": "Normative expectations (oracle source)",
        "implementation": "Implementation (current behavior, not an oracle)",
    },
    "characterization": {
        "normative": "Normative expectations (for comparison)",
        "implementation": "Implementation behavior to characterize",
    },
}
COMMON_LABELS = {
    "interfaces": "Interfaces",
    "tests": "Existing test definitions",
    "runs": "Test runs",
    "fixtures": "Test fixtures",
    "instructions": "Execution instructions (untrusted text, never executed by C1)",
    "discrepancies": "Recorded discrepancies",
}


def section_labels(goal: str) -> dict[str, str]:
    return {**COMMON_LABELS, **SECTION_LABELS[goal]}


def render_software_structured(
    base: dict[str, Any], units: list[dict[str, Any]], bounds: dict[str, Any]
) -> dict[str, Any]:
    selected = public_value(units)
    citations: dict[int, dict[str, Any]] = {}
    for unit in selected:
        for citation in unit_citations(unit):
            citations.setdefault(citation["n"], citation)
    sections: dict[str, list[dict[str, Any]]] = {name: [] for name in UNIT_SECTIONS}
    for unit in selected:
        sections[unit["section"]].append(unit)
    goal = base["interpretation"]["goal"]
    return {
        "title": "Test-development context: " + base.get("anchor_label", ""),
        "interpretation": public_value(base["interpretation"]),
        "goal_statement": GOAL_STATEMENTS[goal],
        "target": public_value(base["target"]),
        "section_labels": section_labels(goal),
        "sections": sections,
        "gaps": public_value(base["gaps"]),
        "sources": [citations[n] for n in sorted(citations)],
        "bounds": public_value(bounds),
        "format_parity_digest": hashlib.sha256(
            canonical_json(parity_identifiers(selected)).encode("utf-8")
        ).hexdigest(),
    }


def _refs(unit: dict[str, Any]) -> str:
    return "".join(f"[^{citation['n']}]" for citation in unit_citations(unit))


def _code(unit: dict[str, Any]) -> str:
    language = unit.get("language") or "text"
    safe_language = language if language.replace("-", "").isalnum() else "text"
    label = "complete unit" if unit.get("code_completeness") == "complete-unit" else "excerpt"
    return _fence(unit["text"], f"{safe_language} {label}")


def _quoted(text: str) -> str:
    return "\n".join("> " + escape_markdown_text(line) for line in text.split("\n"))


def _part_lines(unit: dict[str, Any]) -> list[str]:
    heading = "#### " + _safe(unit.get("path") or unit["document_id"])
    if unit.get("symbol"):
        heading += " — " + _safe(unit["symbol"].get("label") or unit["symbol"]["id"])
    lines = [heading + _refs(unit)]
    metadata = {
        key: unit[key]
        for key in (
            "id",
            "kind",
            "role",
            "part_id",
            "document_id",
            "commit",
            "target_member",
            "part_kind",
            "code_completeness",
            "symbol",
            "range",
            "referenced_at",
            "test_case",
            "status",
            "matching_results",
            "verifies",
            "fixture_for",
            "basis",
        )
        if key in unit
    }
    lines.append("Unit: " + _safe(metadata))
    if unit.get("untrusted"):
        lines.append("Untrusted instruction text (stored data; C1 never executes it):")
        lines.append(_fence(unit["text"], "text"))
    elif "code_completeness" in unit:
        lines.append(_code(unit))
    else:
        lines.append(_quoted(unit["text"]))
    return lines


def _unit_lines(unit: dict[str, Any]) -> list[str]:
    if "part_id" in unit:
        return _part_lines(unit)
    if unit["kind"] == "operation":
        operation = unit["operation"]
        return [
            "#### "
            + _safe(operation.get("operation_id"))
            + " "
            + _safe((operation.get("http_method") or "").upper())
            + " "
            + _safe(operation.get("path_template"))
            + _refs(unit),
            "Unit: "
            + _safe({key: unit[key] for key in ("id", "kind", "role", "operation", "basis")}),
        ]
    if unit["kind"] == "test-run":
        heading = (
            "#### Run "
            + _safe(unit["run_id"])
            + ": "
            + _safe(unit.get("result"))
            + "; "
            + _safe(unit["match"])
            + "; "
            + _safe(unit["integration_mode"])
        )
        if unit["integration_mode"] == "mocked":
            heading += (
                " (mocked products: "
                + _safe([item.get("label") or item["id"] for item in unit["mocked_products"]])
                + "; not integration evidence)"
            )
        elif unit["integration_evidence"]:
            heading += " (integration evidence for the target)"
        return [
            heading + _refs(unit),
            "Unit: " + _safe({key: value for key, value in unit.items() if key != "citations"}),
        ]
    if unit["kind"] == "test-definition":
        return [
            "#### Test case "
            + _safe(unit["test_case"].get("label") or unit["test_case"]["id"])
            + ": "
            + _safe(unit["status"]),
            "Unit: " + _safe({key: value for key, value in unit.items() if key != "citations"}),
            "No definition of this test case is in the target snapshots.",
        ]
    if unit["kind"] == "discrepancy":
        lines = [
            "#### Discrepancy " + _safe(unit["assertion_id"]) + _refs(unit),
            "Unit: " + _safe({key: value for key, value in unit.items() if key != "citations"}),
        ]
        for citation in unit.get("citations", []):
            if "quote" in citation:
                lines.append("Quoted from " + _safe(citation["path"]) + f"[^{citation['n']}]:")
                lines.append(_quoted(citation["quote"]))
        return lines
    return ["Unit: " + _safe(unit)]


def render_software_markdown(package: dict[str, Any]) -> str:
    """Fixed sections; stored text is fenced or quoted and never becomes markup."""
    sections = ["# " + _safe(package["title"]), "## Interpretation"]
    sections.extend(
        "- " + _safe(key) + ": " + _safe(value) for key, value in package["interpretation"].items()
    )
    sections.append(_safe(package["goal_statement"]))
    sections.append("## Target")
    sections.extend(
        "- " + _safe(key) + ": " + _safe(value) for key, value in package["target"].items()
    )
    for name in UNIT_SECTIONS:
        sections.append("## " + _safe(package["section_labels"][name]))
        for unit in package["sections"][name]:
            sections.extend(_unit_lines(unit))
    sections.append("## Gaps")
    sections.extend("- " + _safe(gap) for gap in package["gaps"])
    sections.append("## Sources")
    sections.extend(
        f"[^{citation['n']}]: "
        + _safe(citation.get("path"))
        + "; "
        + _safe({key: value for key, value in citation.items() if key not in {"n", "quote"}})
        for citation in package["sources"]
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


# M10 support packages -----------------------------------------------------------------

SUPPORT_LABELS = {
    "guidance": "Applicable documentation (official guidance)",
    "warnings": "Known warnings for the target",
    "other-target-documentation": "Documentation for other targets (metadata only)",
    "implementation": "Implementation evidence (not a supported procedure)",
    "configuration": "Configuration evidence",
    "interfaces": "Interfaces",
    "observed-tests": "Observed test runs",
    "interpretations": "Attributed interpretations",
}


def render_support_structured(
    base: dict[str, Any], units: list[dict[str, Any]], bounds: dict[str, Any]
) -> dict[str, Any]:
    selected = public_value(units)
    citations: dict[int, dict[str, Any]] = {}
    for unit in selected:
        for citation in unit_citations(unit):
            citations.setdefault(citation["n"], citation)
    names = [name for name in base["sections"] if name in SUPPORT_LABELS]
    sections: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
    for unit in selected:
        sections[unit["section"]].append(unit)
    return {
        "title": base["title"],
        "interpretation": public_value(base["interpretation"]),
        "publication": base["publication"],
        "target": public_value(base["target"]),
        "section_labels": {name: SUPPORT_LABELS[name] for name in names},
        "sections": sections,
        "missing_aspects": public_value(base["missing_aspects"]),
        "gaps": public_value(base["gaps"]),
        "sources": [citations[n] for n in sorted(citations)],
        "bounds": public_value(bounds),
        "format_parity_digest": hashlib.sha256(
            canonical_json(parity_identifiers(selected)).encode("utf-8")
        ).hexdigest(),
    }


def _support_unit_lines(unit: dict[str, Any]) -> list[str]:
    if "part_id" in unit:
        lines = _part_lines(unit)
        lines.insert(1, "Label: " + _safe(unit.get("label", "")))
        return lines
    heading = {
        "applicability-warning": lambda u: (
            "#### Warning: "
            + _safe(u["document"]["title"])
            + " is "
            + _safe(u["statement"])
            + " ("
            + _safe(u["snapshot"].get("label") or u["snapshot"]["id"])
            + ")"
        ),
        "other-target-document": lambda u: (
            "#### " + _safe(u["document"]["title"]) + ": " + _safe(u["statement"])
        ),
        "configuration": lambda u: (
            "#### Configuration "
            + _safe(u["configuration"].get("name"))
            + " ("
            + _safe(u["label"])
            + ")"
        ),
        "aspect-claim": lambda u: (
            "#### "
            + _safe(u["symbol"].get("label"))
            + " addresses "
            + _safe(u["aspect"]["label"])
            + " (attributed interpretation)"
        ),
    }.get(unit["kind"])
    if heading is None:
        return _unit_lines(unit)
    lines = [
        heading(unit) + _refs(unit),
        "Unit: " + _safe({key: value for key, value in unit.items() if key != "citations"}),
    ]
    for citation in unit.get("citations", []):
        if "quote" in citation:
            lines.append("Quoted from " + _safe(citation["path"]) + f"[^{citation['n']}]:")
            lines.append(_quoted(citation["quote"]))
    return lines


def render_support_markdown(package: dict[str, Any]) -> str:
    sections = ["# " + _safe(package["title"]), "## Interpretation"]
    sections.extend(
        "- " + _safe(key) + ": " + _safe(value) for key, value in package["interpretation"].items()
    )
    sections.append(_safe(package["publication"]))
    sections.append("## Target")
    sections.extend(
        "- " + _safe(key) + ": " + _safe(value) for key, value in package["target"].items()
    )
    for name, label in package["section_labels"].items():
        sections.append("## " + _safe(label))
        for unit in package["sections"][name]:
            sections.extend(_support_unit_lines(unit))
    sections.append("## Missing aspects")
    sections.extend(
        "- "
        + _safe(item["aspect"]["label"])
        + " ("
        + _safe(item["aspect"]["id"])
        + "): "
        + _safe(item["status"])
        for item in package["missing_aspects"]
    )
    if package["gaps"]:
        sections.extend("- " + _safe(gap) for gap in package["gaps"])
    sections.append("## Sources")
    sections.extend(
        f"[^{citation['n']}]: "
        + _safe(citation.get("path"))
        + "; "
        + _safe({key: value for key, value in citation.items() if key not in {"n", "quote"}})
        for citation in package["sources"]
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


# M11 documentation-update packages ----------------------------------------------------

UPDATE_LABELS = {
    "document-structure": "Existing documentation and its applicability per target snapshot",
    "responsibilities": "Responsibilities per repository (implementation evidence)",
    "interface-contract": "Interface contract and explicit links",
    "configuration": "Configuration",
    "tests-and-runs": "Test runs",
    "changes": "Review candidates and recorded discrepancies",
    "drafts": "Documentation drafts (C1 records; not external publication)",
    "compatibility": "Compatibility per pair of target snapshots",
}


def render_update_structured(
    base: dict[str, Any], units: list[dict[str, Any]], bounds: dict[str, Any]
) -> dict[str, Any]:
    selected = public_value(units)
    citations: dict[int, dict[str, Any]] = {}
    for unit in selected:
        for citation in unit_citations(unit):
            citations.setdefault(citation["n"], citation)
    names = [name for name in base["sections"] if name in UPDATE_LABELS]
    sections: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
    for unit in selected:
        sections[unit["section"]].append(unit)
    return {
        "title": base["title"],
        "interpretation": public_value(base["interpretation"]),
        "publication": base["publication"],
        "target": public_value(base["target"]),
        "section_labels": {name: UPDATE_LABELS[name] for name in names},
        "sections": sections,
        "gaps": public_value(base["gaps"]),
        "sources": [citations[n] for n in sorted(citations)],
        "bounds": public_value(bounds),
        "format_parity_digest": hashlib.sha256(
            canonical_json(parity_identifiers(selected)).encode("utf-8")
        ).hexdigest(),
    }


def _update_unit_lines(unit: dict[str, Any]) -> list[str]:
    if unit["kind"] == "document-part":
        lines = _part_lines(unit)
        lines.insert(
            1,
            "Applicability: "
            + _safe({key: value["state"] for key, value in unit["applicability"].items()}),
        )
        return lines
    if unit["kind"] in {"code-unit", "dependency-unit", "contract-part"} or unit["kind"] in {
        "operation",
        "test-run",
        "discrepancy",
    }:
        return _unit_lines(unit)
    headings: dict[str, Callable[[dict[str, Any]], str]] = {
        "other-target-document": lambda u: (
            "#### " + _safe(u["document"]["title"]) + ": " + _safe(u["statement"])
        ),
        "configuration": lambda u: "#### Configuration " + _safe(u["configuration"].get("name")),
        "applicability-record": lambda u: (
            "#### " + _safe(u["state"]) + " (" + _safe(u["basis"]) + "): " + _safe(u["statement"])
        ),
        "draft": lambda u: (
            "#### Draft "
            + _safe(u["title"])
            + ": "
            + _safe(u["draft_state"])
            + ", "
            + _safe(u["publication_state"])
        ),
        "compatibility": lambda u: (
            "#### " + _safe(u["pair"]) + ": " + _safe(u["status"]) + ". " + _safe(u["statement"])
        ),
    }
    heading = headings[unit["kind"]]
    lines = [
        heading(unit) + _refs(unit),
        "Unit: "
        + _safe({key: value for key, value in unit.items() if key not in {"citations", "parts"}}),
    ]
    for part in unit.get("parts", []):
        lines.append("Draft part " + _safe(part["part_id"]) + ":")
        lines.append(_quoted(part["text"]))
        lines.append("Derived from: " + _safe(part["derived_from"]))
    return lines


def render_update_markdown(package: dict[str, Any]) -> str:
    sections = ["# " + _safe(package["title"]), "## Interpretation"]
    sections.extend(
        "- " + _safe(key) + ": " + _safe(value) for key, value in package["interpretation"].items()
    )
    sections.append(_safe(package["publication"]))
    sections.append("## Target")
    sections.extend(
        "- " + _safe(key) + ": " + _safe(value) for key, value in package["target"].items()
    )
    for name, label in package["section_labels"].items():
        sections.append("## " + _safe(label))
        for unit in package["sections"][name]:
            sections.extend(_update_unit_lines(unit))
    sections.append("## Gaps")
    sections.extend("- " + _safe(gap) for gap in package["gaps"])
    sections.append("## Sources")
    sections.extend(
        f"[^{citation['n']}]: "
        + _safe(citation.get("path"))
        + "; "
        + _safe({key: value for key, value in citation.items() if key not in {"n", "quote"}})
        for citation in package["sources"]
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
