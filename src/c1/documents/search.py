"""Exact lexical matching over already authorized documents and parts."""

from __future__ import annotations

from collections.abc import Sequence

from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import C1, DCTERMS
from c1.query.filters import _prefix_text


def _literals(node: NodeRecord, predicate: str) -> tuple[str, ...]:
    return tuple(
        value.lexical
        for value in node.properties.get(predicate, ())
        if isinstance(value, LiteralValue)
    )


def _contains(values: tuple[str, ...], needle: str) -> bool:
    folded = _prefix_text(needle)
    return any(folded in _prefix_text(value) for value in values)


def part_matches(part: NodeRecord, text_contains: str) -> bool:
    """Match a readable part's exact normalized text or title substring."""
    if not text_contains:
        raise ValueError("text_contains must not be empty")
    return _contains(
        _literals(part, C1 + "text") + _literals(part, DCTERMS + "title"),
        text_contains,
    )


def search_document(
    document: NodeRecord,
    readable_parts: Sequence[NodeRecord],
    *,
    text_contains: str | None = None,
    title: str | None = None,
) -> dict[str, object] | None:
    """Return a snippet-free match explanation, or None for a nonmatch.

    The caller alone decides which records are readable. A title filter and a
    text filter combine with AND; the text filter matches the document title
    or any supplied part's title or text.
    """
    if title == "" or text_contains == "":
        raise ValueError("search terms must not be empty")
    document_titles = _literals(document, DCTERMS + "title")
    if title is not None and not _contains(document_titles, title):
        return None
    title_match = bool(text_contains and _contains(document_titles, text_contains))
    matched_parts = [
        part.id
        for part in readable_parts
        if text_contains is not None and part_matches(part, text_contains)
    ]
    if text_contains is not None and not title_match and not matched_parts:
        return None
    return {
        "matched_part_ids": matched_parts,
        "match": {"title": title_match, "parts": matched_parts},
    }
