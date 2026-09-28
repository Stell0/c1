"""Pure rendering of an already authorized, ordered document projection.

This module never fetches parts. The caller must authorize each part with its
current binding before passing it here, including for historical revisions.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import C1, DCTERMS

_MARKDOWN_SPECIAL = frozenset("\\`*_{}[]()#+-.!>|~")
_BACKTICKS = re.compile(r"`+")
_URL = re.compile(r"(?i)\b(?:https?://|www\.)")
_COMMAND = re.compile(r"\$\(|\b(?:curl|wget)\b[^\n]*\|\s*(?:sh|bash)\b")
_LANGUAGE = re.compile(r"[A-Za-z0-9_+.-]+\Z")


def _literal(node: NodeRecord, predicate: str) -> str | None:
    return next(
        (
            value.lexical
            for value in node.properties.get(predicate, ())
            if isinstance(value, LiteralValue)
        ),
        None,
    )


def escape_markdown_text(value: str) -> str:
    """Emit untrusted prose without live HTML, Markdown links, or images."""
    escaped: list[str] = []
    for character in value:
        if character == "&":
            escaped.append("&amp;")
        elif character == "<":
            escaped.append("&lt;")
        elif character == ">":
            escaped.append("&gt;")
        elif character in _MARKDOWN_SPECIAL:
            escaped.append("\\" + character)
        else:
            escaped.append(character)
    # GFM auto-links bare URLs even when Markdown link delimiters are escaped.
    return _URL.sub(lambda match: match.group().replace(":", "\\:"), "".join(escaped))


def _fence(value: str, info: str) -> str:
    length = max((len(match.group()) + 1 for match in _BACKTICKS.finditer(value)), default=3)
    length = max(3, length)
    marker = "`" * length
    # The text format carries exact source bytes. Markdown uses entity escapes
    # so no raw HTML can survive if a consumer mishandles the code fence.
    safe = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"{marker}{info}\n{safe}\n{marker}"


def _markdown_part(part: NodeRecord) -> str:
    kind = _literal(part, C1 + "partKind") or "text"
    text = _literal(part, C1 + "text") or ""
    title = _literal(part, DCTERMS + "title")
    base, _, language = kind.partition(":")

    if base in {"code", "code-unit"}:
        safe_language = language if _LANGUAGE.fullmatch(language) else "text"
        label = "excerpt" if base == "code" else "complete unit"
        return _fence(text, f"{safe_language} {label}")
    display = title if base.startswith("heading-") and title is not None else text
    if base in {"table", "metadata"} or _COMMAND.search(display):
        return _fence(display, "text")
    if base.startswith("heading-") and base[-1:] in "123456" and len(base) == 9:
        level = int(base[-1])
        return "#" * level + " " + escape_markdown_text(title if title is not None else text)

    lines = [escape_markdown_text(line) for line in text.split("\n")]
    if base == "quote":
        return "\n".join("> " + line for line in lines)
    if base == "list-item":
        return "- " + "\n  ".join(lines)
    return "\n".join(lines)


def render_document(
    parts: Sequence[NodeRecord], *, format: Literal["markdown", "text"] = "markdown"
) -> str:
    """Render the supplied authorized parts in their supplied order."""
    if format == "markdown":
        return "\n\n".join(_markdown_part(part) for part in parts)
    if format == "text":
        return "\n\n".join(
            (_literal(part, DCTERMS + "title") or _literal(part, C1 + "text") or "")
            if (_literal(part, C1 + "partKind") or "").startswith("heading-")
            else (_literal(part, C1 + "text") or "")
            for part in parts
        )
    raise ValueError("unsupported render format")
