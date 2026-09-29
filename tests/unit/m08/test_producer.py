"""M08 W4: pure producer mappings (no services)."""

from __future__ import annotations

import pytest

from scripts import software_producer as sp

PRINCIPALS = {
    "indexer": "user:c1-dev.indexer",
    "analyzer": "user:c1-dev.analyzer",
    "ci": "user:c1-dev.ci",
}


def _symbol(text: str) -> sp.ScipSymbol:
    parsed = sp.parse_symbol(text)
    assert parsed is not None
    return parsed


def test_scip_symbol_grammar_and_subset() -> None:
    symbol = sp.parse_symbol("scip-python python ledger a1 `ledger.api`/validate().")
    assert symbol == sp.ScipSymbol(
        "scip-python", "python", "ledger", "a1", "`ledger.api`/validate()."
    )
    assert symbol.kind == "function"
    assert symbol.display == "ledger.api.validate"
    assert sp.parse_symbol("local 0") is None
    assert _symbol("scip-python python ledger a1 `ledger.models`/Invoice#").kind == "type"
    # Parameters and module terms are outside the CodeSymbol subset.
    assert _symbol("scip-python python ledger a1 `ledger.api`/validate().(amount)").kind is None
    assert _symbol("scip-python python ledger a1 `ledger.api`/__init__:").kind is None
    # A double space escapes a space inside a field.
    spaced = sp.parse_symbol("scheme python my  pkg 1.0 a/b().")
    assert spaced is not None and spaced.package == "my pkg"
    with pytest.raises(ValueError):
        sp.parse_symbol("scheme python")


def test_occurrence_ranges_accept_packed_and_typed_forms() -> None:
    assert sp.occurrence_range({"range": [3, 4, 12]}) == (3, 4, 3, 12)
    assert sp.occurrence_range({"range": [3, 0, 5, 2]}) == (3, 0, 5, 2)
    typed = {
        "range": [9, 9, 9],
        "TypedRange": {"SingleLineRange": {"line": 3, "start_character": 4, "end_character": 12}},
    }
    assert sp.occurrence_range(typed) == (3, 4, 3, 12)
    with pytest.raises(ValueError):
        sp.occurrence_range({})
    assert sp.roles(0x1 | 0x8) == ["definition", "read-access"]
    assert sp.roles(0) == ["reference"]
    assert sp.position_encoding({}) == "unspecified"
    assert sp.position_encoding({"position_encoding": 1}) == "utf-8"


def test_python_parts_are_exact_complete_units_and_excerpts() -> None:
    text = '"""doc"""\n\nimport os\n\n\ndef a():\n    return 1\n\n\nclass B:\n    x = 1\n'
    parts = sp.python_parts(text, [(5, 6), (9, 10)])
    assert [part.kind for part in parts] == ["code:python", "code-unit:python", "code-unit:python"]
    assert parts[1].text == "def a():\n    return 1\n"
    assert parts[2].text == "class B:\n    x = 1\n"
    for part in parts:
        assert part.text in text
    assert sp.order_key(1) == "00001u" and not sp.order_key(10).endswith("0")


def test_markdown_sections_keep_exact_text_and_ignore_fenced_headings() -> None:
    text = "# Title\n\nIntro.\n\n## Run\n\n```sh\n# not a heading\npytest\n```\n"
    parts = sp.markdown_parts(text)
    assert [part.kind for part in parts] == ["heading-1", "text", "heading-2", "text"]
    assert "# not a heading" in parts[3].text
    assert "".join(part.text for part in parts) == text


def test_junit_subset() -> None:
    passing = b'<testsuite><testcase name="t"/></testsuite>'
    failing = b'<testsuite><testcase name="t"><failure message="x"/></testcase></testsuite>'
    assert sp.junit_result(passing) == "pass"
    assert sp.junit_result(failing) == "fail"
    with pytest.raises(ValueError):
        sp.junit_result(b'<!DOCTYPE x [<!ENTITY a "b">]><testsuite/>')
    with pytest.raises(ValueError):
        sp.junit_result(b"<testsuite><testcase/><testcase/></testsuite>")


def test_planner_output_is_deterministic_and_scope_safe() -> None:
    runs = sp.Planner(sp.load_inputs(), PRINCIPALS).runs()
    again = sp.Planner(sp.load_inputs(), PRINCIPALS).runs()
    assert [run.records for run in runs] == [run.records for run in again]
    ids = [record["id"] for run in runs for record in (*run.records, *run.coverage_records())]
    assert len(ids) == len(set(ids))
    # Coverage digests cover only their own scope, so a hidden scope cannot
    # change what another scope's audience reads.
    b1 = next(run for run in runs if run.key == "scip/b1")
    shop = next(r for r in b1.coverage_records() if r["scope"] == "sw-shop")
    twin = sp.without_scopes([b1], {"sw-restricted"})[0]
    twin_shop = next(r for r in twin.coverage_records() if r["scope"] == "sw-shop")
    assert shop == twin_shop
    assert all(record["scope"] != "sw-restricted" for record in twin.records)
    # The syntax-error file is reported and its scope coverage is partial.
    b2 = next(run for run in runs if run.key == "scip/b2")
    states = {
        r["scope"]: r["properties"][sp.S + "coverageState"][0]["lexical"]
        for r in b2.coverage_records()
    }
    assert states == {"sw-shop": "partial", "sw-restricted": "complete"}


def test_idempotency_key_binds_batch_and_base() -> None:
    run = sp.Planner(sp.load_inputs(), PRINCIPALS).runs()[0]
    batch = sp.batches(run)[0]
    key = sp.idempotency_key(run, 0, batch, "branch:one")
    assert key == sp.idempotency_key(run, 0, batch, "branch:one")
    assert key != sp.idempotency_key(run, 0, batch, "branch:two")
    assert key != sp.idempotency_key(run, 0, batch[:-1], "branch:one")
    assert key.startswith("sw1-") and len(key) <= 128
