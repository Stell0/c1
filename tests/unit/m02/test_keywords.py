import json
from pathlib import Path

from c1.model.keywords import Keyword, coalesce, match_all, match_any, normalize

VECTORS = Path(__file__).parent / "vectors" / "keywords.json"


def test_keyword_vectors() -> None:
    vectors = json.loads(VECTORS.read_text())
    for text, expected in vectors["normalize"]:
        assert normalize(text) == expected
    keywords = [Keyword.model_validate(item) for item in vectors["coalesce"]]
    retained, diagnostics = coalesce(keywords)
    assert [item.text for item in retained] == vectors["coalesced_text"]
    assert [item.code for item in diagnostics] == ["C1-KW-001"]
    for case in vectors["matches"]:
        query = [Keyword.model_validate(item) for item in case["query"]]
        assert match_any(retained, query) is case["any"]
        assert match_all(retained, query) is case["all"]
    assert not match_any([Keyword(text="müller")], [Keyword(text="muller")])


def test_keyword_record_retains_original_and_version() -> None:
    keyword = Keyword(text="  ﬁle  ", language="EN-us")
    assert keyword.text == "  ﬁle  "
    assert keyword.normalized == "file"
    assert keyword.language == "en-us"
    assert keyword.normalization_version == "c1-kw-1"
    assert keyword.model_dump()["text"] == "  ﬁle  "
