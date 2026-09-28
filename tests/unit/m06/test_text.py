"""M06-D3 lossless text, structural validation, and selectors."""

from __future__ import annotations

import asyncio
import hashlib

from c1.authorization.models import Decision
from c1.changes.models import ChangeSet, CreateOperation, ReplaceOperation
from c1.changes.validation import validate_changeset
from c1.documents.text import MAX_UTF8_BYTES, digest, length
from c1.documents.validation import document_diagnostics, selector_diagnostics
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry
from c1.model.records import DocumentPartRecord, DocumentRecord, EvidenceRecord

BASE = "urn:c1:instance:dev:"
C1 = "urn:c1:ns:core#"
OA = "http://www.w3.org/ns/oa#"
XSD = "http://www.w3.org/2001/XMLSchema#"
DOC = BASE + "document/one"


def lit(value: str, datatype: str = XSD + "string") -> LiteralValue:
    return LiteralValue(lexical=value, datatype=datatype)


def part(key: str, body: str, *, name: str = "one", kind: str = "text") -> NodeRecord:
    return DocumentPartRecord(
        id=BASE + "documentpart/" + name,
        document_id=DOC,
        order_key=key,
        text=body,
        kind=kind,
    ).to_node()


def codes(record: NodeRecord) -> list[str]:
    return [item.code for item in document_diagnostics(record, "/record")]


def test_exact_text_bytes_digest_and_limits() -> None:
    body = "e\u0301\r\n\t  😀"
    assert length(body) == len(body)
    assert digest(body) == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert codes(part("A", body)) == []
    assert codes(part("A", "x" * MAX_UTF8_BYTES)) == []
    assert "C1-DC-004" in codes(part("A", "x" * (MAX_UTF8_BYTES + 1)))
    assert "C1-DC-004" in codes(part("A", "😀" * (MAX_UTF8_BYTES // 4 + 1)))
    assert "C1-DC-003" in codes(part("A", "a\x00b"))
    assert "C1-DC-003" in codes(part("A", "a\x7fb"))
    for code_point in range(0x80, 0xA0):
        assert codes(part("A", "a" + chr(code_point) + "b")) == ["C1-DC-003"]


def test_key_and_kind_validation() -> None:
    assert codes(part("A0", "hello")) == ["C1-DC-002"]
    assert codes(part("A", "hello", kind="code:python")) == []
    assert codes(part("A", "hello", kind="heading-7")) == ["C1-DC-007"]


def test_selectors_use_code_point_offsets_and_exact_substring() -> None:
    source = part("A", "😀abc")
    quote = NodeRecord(
        id=BASE + "selector/quote",
        types=[C1 + "Selector"],
        properties={C1 + "selectorKind": [lit("TextQuoteSelector")], OA + "exact": [lit("abc")]},
    )
    position = NodeRecord(
        id=BASE + "selector/position",
        types=[C1 + "Selector"],
        properties={
            C1 + "selectorKind": [lit("TextPositionSelector")],
            OA + "start": [lit("1", XSD + "integer")],
            OA + "end": [lit("4", XSD + "integer")],
        },
    )
    assert selector_diagnostics(quote, source, "/selector") == []
    assert selector_diagnostics(position, source, "/selector") == []
    bad = quote.model_copy(
        update={"properties": {**quote.properties, OA + "exact": [lit("missing")]}}
    )
    assert [item.code for item in selector_diagnostics(bad, source, "/selector")] == ["C1-DC-005"]
    bad_pos = position.model_copy(
        update={"properties": {**position.properties, OA + "end": [lit("5", XSD + "integer")]}}
    )
    assert [item.code for item in selector_diagnostics(bad_pos, source, "/selector")] == [
        "C1-DC-005"
    ]


def test_changeset_accepts_equal_order_ranks_for_distinct_parts() -> None:
    async def case() -> None:
        doc = DocumentRecord(id=DOC, title=lit("Test")).to_node()
        first = part("A", "first body")
        second = part("A", "second body", name="second")

        async def reference(identifier: str, _revision: str) -> NodeRecord | None:
            return doc if identifier == DOC else None

        async def allow(_operation: object) -> Decision:
            return Decision(True, "allowed")

        changeset = ChangeSet(
            id="change-one",
            author="author",
            base_revision="branch:base",
            operations=[
                CreateOperation(record=item.model_dump(mode="json"), scope_id="scope")
                for item in (first, second)
            ],
            created="2026-09-28T00:00:00Z",
            updated="2026-09-28T00:00:00Z",
        )
        result = await validate_changeset(
            changeset,
            registry=ProfileRegistry(),
            resolve_reference=reference,
            permission_preview=allow,
        )
        assert result.accepted
        assert sorted((first, second), key=lambda item: ("A", item.id)) == [first, second]

        repeated_id = changeset.model_copy(
            update={
                "operations": [
                    CreateOperation(record=first.model_dump(mode="json"), scope_id="scope"),
                    CreateOperation(record=first.model_dump(mode="json"), scope_id="scope"),
                ]
            }
        )
        identity_result = await validate_changeset(
            repeated_id,
            registry=ProfileRegistry(),
            resolve_reference=reference,
            permission_preview=allow,
        )
        assert "C1-IX-030" in [item.code for item in identity_result.diagnostics]

    asyncio.run(case())


def test_replacement_can_keep_or_take_an_existing_order_rank() -> None:
    async def case() -> None:
        doc = DocumentRecord(id=DOC, title=lit("Test")).to_node()
        old = part("A", "previous text")

        async def reference(identifier: str, _revision: str) -> NodeRecord | None:
            return doc if identifier == DOC else old if identifier == old.id else None

        async def allow(_operation: object) -> Decision:
            return Decision(True, "allowed")

        async def validate(replacement: NodeRecord) -> list[str]:
            change = ChangeSet(
                id="change-two",
                author="author",
                base_revision="branch:base",
                operations=[
                    ReplaceOperation(
                        resource_id=old.id,
                        record=replacement.model_dump(mode="json"),
                        reason="edit",
                    )
                ],
                created="2026-09-28T00:00:00Z",
                updated="2026-09-28T00:00:00Z",
            )
            result = await validate_changeset(
                change,
                registry=ProfileRegistry(),
                resolve_reference=reference,
                permission_preview=allow,
            )
            return [item.code for item in result.diagnostics]

        assert await validate(part("A", "new text")) == []
        assert await validate(part("B", "new text")) == []
        assert await validate(part("B0", "new text")) == ["C1-DC-002"]

    asyncio.run(case())


def test_evidence_source_revision_matches_readable_parent_document() -> None:
    async def case() -> None:
        doc = DocumentRecord(id=DOC, title=lit("Test"), source_revision="source-v7").to_node()
        source_part = part("A", "readable part")
        assertion = NodeRecord(id=BASE + "assertion/one", types=[C1 + "Assertion"], properties={})

        async def allow(_operation: object) -> Decision:
            return Decision(True, "allowed")

        async def validate(revision: str, *, document_readable: bool = True) -> list[str]:
            evidence = EvidenceRecord(
                id=BASE + "evidence/one",
                assertion_id=assertion.id,
                source_id=source_part.id,
                source_revision=revision,
            ).to_node()

            async def reference(identifier: str, _revision: str) -> NodeRecord | None:
                if identifier == source_part.id:
                    return source_part
                if identifier == doc.id:
                    return doc if document_readable else None
                return assertion if identifier == assertion.id else None

            change = ChangeSet(
                id="change-evidence",
                author="author",
                base_revision="branch:base",
                operations=[
                    CreateOperation(record=evidence.model_dump(mode="json"), scope_id="scope")
                ],
                created="2026-09-28T00:00:00Z",
                updated="2026-09-28T00:00:00Z",
            )
            result = await validate_changeset(
                change,
                registry=ProfileRegistry(),
                resolve_reference=reference,
                permission_preview=allow,
            )
            return [item.code for item in result.diagnostics]

        assert await validate("source-v7") == []
        assert await validate("source-v6") == ["C1-DC-009"]
        assert await validate("source-v7", document_readable=False) == ["C1-CS-010"]
        assert await validate("guessed-v1", document_readable=False) == ["C1-CS-010"]

    asyncio.run(case())


def test_native_document_evidence_uses_base_knowledge_revision() -> None:
    async def case() -> None:
        doc = DocumentRecord(id=DOC, title=lit("Native")).to_node()
        source_part = part("A", "body")
        assertion = NodeRecord(id=BASE + "assertion/one", types=[C1 + "Assertion"], properties={})

        async def reference(identifier: str, _revision: str) -> NodeRecord | None:
            records = {doc.id: doc, source_part.id: source_part, assertion.id: assertion}
            return records.get(identifier)

        async def allow(_operation: object) -> Decision:
            return Decision(True, "allowed")

        evidence = EvidenceRecord(
            id=BASE + "evidence/native",
            assertion_id=assertion.id,
            source_id=source_part.id,
            source_revision="branch:base",
        ).to_node()
        change = ChangeSet(
            id="change-native",
            author="author",
            base_revision="branch:base",
            operations=[CreateOperation(record=evidence.model_dump(mode="json"), scope_id="scope")],
            created="2026-09-28T00:00:00Z",
            updated="2026-09-28T00:00:00Z",
        )
        result = await validate_changeset(
            change,
            registry=ProfileRegistry(),
            resolve_reference=reference,
            permission_preview=allow,
        )
        assert result.accepted

    asyncio.run(case())
