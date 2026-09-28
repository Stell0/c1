from __future__ import annotations

import pytest

from c1.documents.search import part_matches, search_document
from c1.model.literals import XSD_STRING, LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import DocumentPartRecord, DocumentRecord


def lit(value: str) -> LiteralValue:
    return LiteralValue(lexical=value, datatype=XSD_STRING)


def document() -> NodeRecord:
    return DocumentRecord(id="urn:test:document", title=lit("Handbook")).to_node()


def part(index: int, text: str, *, title: str | None = None):  # type: ignore[no-untyped-def]
    return DocumentPartRecord(
        id=f"urn:test:part:{index}",
        document_id="urn:test:document",
        order_key=str(index),
        text=text,
        title=lit(title) if title is not None else None,
    ).to_node()


def test_only_supplied_readable_parts_influence_match() -> None:
    visible = part(1, "Everyday notes")
    hidden = part(2, "zebra-token")
    assert search_document(document(), [visible], text_contains="zebra-token") is None
    assert search_document(document(), [visible], text_contains="DAY notes") == {
        "matched_part_ids": [visible.id],
        "match": {"title": False, "parts": [visible.id]},
    }
    assert search_document(document(), [visible, hidden], text_contains="zebra-token") == {
        "matched_part_ids": [hidden.id],
        "match": {"title": False, "parts": [hidden.id]},
    }


def test_normalization_and_title_filters() -> None:
    titled = part(1, "body", title="Ｆｉｌｅ notes")
    assert part_matches(titled, "file")
    assert search_document(document(), [titled], text_contains="hand", title="BOOK") == {
        "matched_part_ids": [],
        "match": {"title": True, "parts": []},
    }
    assert search_document(document(), [titled], text_contains="file", title="missing") is None
    assert search_document(document(), [titled], text_contains="file") == {
        "matched_part_ids": [titled.id],
        "match": {"title": False, "parts": [titled.id]},
    }
    assert not part_matches(titled, "files")


def test_empty_terms_are_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        part_matches(part(1, "x"), "")
    with pytest.raises(ValueError, match="empty"):
        search_document(document(), [], text_contains="")
    with pytest.raises(ValueError, match="empty"):
        search_document(document(), [], title="")
