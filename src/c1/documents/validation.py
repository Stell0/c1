"""Pure M06 document and part invariants."""

from __future__ import annotations

import re

from c1.documents.order import valid
from c1.documents.text import MAX_UTF8_BYTES, invalid_control, utf8_size
from c1.model.diagnostics import Diagnostic
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord

C1 = "urn:c1:ns:core#"
OA = "http://www.w3.org/ns/oa#"
DOCUMENT = C1 + "Document"
PART = C1 + "DocumentPart"
EVIDENCE = C1 + "Evidence"
SELECTOR = C1 + "Selector"

_PART_KINDS = frozenset(
    {"text", "quote", "list-item", "table", "metadata", "code", "code-unit"}
    | {f"heading-{level}" for level in range(1, 7)}
)
_CODE_KIND = re.compile(r"code(?:-unit)?:[A-Za-z0-9][A-Za-z0-9_+.#-]{0,63}")


def literal(record: NodeRecord, predicate: str) -> str | None:
    values = record.properties.get(predicate, [])
    if len(values) != 1 or not isinstance(values[0], LiteralValue):
        return None
    return values[0].lexical


def iri(record: NodeRecord, predicate: str) -> str | None:
    values = record.properties.get(predicate, [])
    return values[0] if len(values) == 1 and isinstance(values[0], str) else None


def _error(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(code=code, severity="error", path=path, message=message)


def document_diagnostics(record: NodeRecord, path: str) -> list[Diagnostic]:
    if PART not in record.types:
        return []
    result: list[Diagnostic] = []
    key = literal(record, C1 + "orderKey")
    if key is None or not valid(key):
        result.append(_error("C1-DC-002", path + "/orderKey", "invalid_order_key"))
    kind = literal(record, C1 + "partKind")
    if kind is not None and kind not in _PART_KINDS and _CODE_KIND.fullmatch(kind) is None:
        result.append(_error("C1-DC-007", path + "/partKind", "invalid_part_kind"))
    body = literal(record, C1 + "text")
    if body is not None:
        if invalid_control(body):
            result.append(_error("C1-DC-003", path + "/text", "control_character"))
        try:
            too_large = utf8_size(body) > MAX_UTF8_BYTES
        except UnicodeEncodeError:
            # Lone surrogate code points cannot be represented by the declared
            # UTF-8 digest/encoding contract.
            result.append(_error("C1-DC-003", path + "/text", "invalid_unicode"))
        else:
            if too_large:
                result.append(_error("C1-DC-004", path + "/text", "part_too_large"))
    return result


def selector_diagnostics(selector: NodeRecord, part: NodeRecord, path: str) -> list[Diagnostic]:
    """Check offsets against the exact source part text, in code points."""
    kind = literal(selector, C1 + "selectorKind")
    body = literal(part, C1 + "text")
    if body is None:
        return [_error("C1-DC-005", path, "selector_mismatch")]
    if kind == "TextQuoteSelector":
        exact = literal(selector, OA + "exact")
        if exact is not None and exact in body:
            return []
    elif kind == "TextPositionSelector":
        start = literal(selector, OA + "start")
        end = literal(selector, OA + "end")
        try:
            first = int(start) if start is not None else -1
            last = int(end) if end is not None else -1
        except ValueError:
            pass
        else:
            if 0 <= first <= last <= len(body):
                return []
    return [_error("C1-DC-005", path, "selector_mismatch")]
