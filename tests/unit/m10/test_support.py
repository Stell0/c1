"""M10 D1–D5: support profile grammar, applicability ordering, missing aspects."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from c1.context.profiles import SoftwareContextProfile, load_any_context_profile
from c1.context.request import ContextRequest, IDSelector, request_digest
from c1.context.support import MISSING_TEXT, SupportSelection, resolve_aspects
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.software.service import Target

S = "urn:c1:ns:software#"
C1 = "urn:c1:ns:core#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
DCT = "http://purl.org/dc/terms/"
SKOS = "http://www.w3.org/2004/02/skos/core#"
XSD = "http://www.w3.org/2001/XMLSchema#"
ROOT = Path(__file__).resolve().parents[3]


def lit(value: str, datatype: str = "string") -> LiteralValue:
    return LiteralValue(lexical=value, datatype=XSD + datatype)


def node(identifier: str, cls: str, properties: Mapping[str, Sequence[Any]]) -> NodeRecord:
    return NodeRecord(
        id=identifier, types=[cls], properties={k: list(v) for k, v in properties.items()}
    )


def profile(name: str) -> SoftwareContextProfile:
    value = load_any_context_profile(ROOT / f"profiles/context/{name}.json")
    assert isinstance(value, SoftwareContextProfile)
    return value


class Store:
    def __init__(self) -> None:
        self.records: dict[str, NodeRecord] = {}
        self.count = 0

    def add(self, record: NodeRecord) -> str:
        self.records[record.id] = record
        return record.id

    def claim(self, subject: str, predicate: str, obj: str, review: str = "reported") -> None:
        self.count += 1
        self.add(
            node(
                f"urn:t:a/{self.count}",
                C1 + "Assertion",
                {
                    RDF + "subject": [subject],
                    RDF + "predicate": [S + predicate],
                    RDF + "object": [obj],
                    C1 + "lifecycle": [lit("active")],
                    C1 + "reviewState": [lit(review)],
                },
            )
        )

    def document(self, key: str, issued: str, parts: list[str]) -> tuple[str, list[str]]:
        doc = self.add(
            node(
                f"urn:t:doc/{key}",
                C1 + "Document",
                {
                    DCT + "title": [lit(key)],
                    C1 + "sourceRevision": [lit("guide:" + key)],
                    DCT + "issued": [lit(issued, "date")],
                },
            )
        )
        ids = [
            self.add(
                node(
                    f"urn:t:part/{key}/{i}",
                    C1 + "DocumentPart",
                    {
                        C1 + "partOfDocument": [doc],
                        C1 + "partKind": [lit("text")],
                        C1 + "text": [lit(text)],
                        C1 + "orderKey": [lit(f"{i:05d}u")],
                    },
                )
            )
            for i, text in enumerate(parts)
        ]
        return doc, ids


def fixture() -> tuple[Store, Target, dict[str, str]]:
    s = Store()
    ids: dict[str, str] = {}
    repo = s.add(node("urn:t:repo", S + "CodeRepository", {SKOS + "prefLabel": [lit("repo")]}))
    for key in ("s1", "s2"):
        ids[key] = s.add(
            node(
                f"urn:t:{key}",
                S + "SourceSnapshot",
                {
                    S + "repositoryRef": [repo],
                    S + "commitId": [lit(key * 20)],
                    SKOS + "prefLabel": [lit(key)],
                },
            )
        )
    ids["op"] = s.add(node("urn:t:op", S + "InterfaceOperation", {SKOS + "prefLabel": [lit("op")]}))
    for key, label in (("retry", "Retry"), ("timeout", "Timeout"), ("config", "Configuration")):
        ids[key] = s.add(
            node(f"urn:t:aspect/{key}", S + "Aspect", {SKOS + "prefLabel": [lit(label)]})
        )
    old, old_parts = s.document("old-applicable", "2026-01-01", ["Old config text."])
    new, _ = s.document("new-other-target", "2026-03-01", ["New text for s2."])
    obsolete, _ = s.document("newest-obsolete", "2026-04-01", ["Obsolete text."])
    reviewed, reviewed_parts = s.document("older-reviewed", "2025-12-01", ["Reviewed text."])
    for doc in (old, new, obsolete, reviewed):
        s.claim(doc, "documents", ids["op"])
    s.claim(old, "describesSnapshot", ids["s1"])
    s.claim(reviewed, "describesSnapshot", ids["s1"], review="confirmed")
    s.claim(new, "describesSnapshot", ids["s2"])
    s.claim(obsolete, "describesSnapshot", ids["s1"])
    s.claim(obsolete, "notApplicableTo", ids["s1"])
    s.claim(old_parts[0], "addressesAspect", ids["config"])
    ids.update(
        old=old, new=new, obsolete=obsolete, reviewed=reviewed, reviewed_part=reviewed_parts[0]
    )
    return s, Target({ids["s1"]: s.records[ids["s1"]]}), ids


def test_applicability_before_age_review_before_recency_and_warnings() -> None:
    s, target, ids = fixture()
    aspects, report = resolve_aspects(
        s.records, ["configuration", "retry", IDSelector(id=ids["timeout"]), "unknown"]
    )
    assert [item["outcome"] for item in report] == [
        "resolved",
        "resolved",
        "resolved",
        "unresolved",
    ]
    selection = SupportSelection(
        s.records,
        target,
        s.records[ids["op"]],
        profile("support-documentation"),
        aspects,
        deadline=time.monotonic() + 30,
    )
    selection.build()
    guidance = [u for u in selection.units if u["section"] == "guidance"]
    # Confirmed review first, then the applicable reported guide; never the newer other-target one.
    assert [u["document_title"] for u in guidance] == ["older-reviewed", "old-applicable"]
    warnings = [u for u in selection.units if u["section"] == "warnings"]
    assert [w["document"]["title"] for w in warnings] == ["newest-obsolete"]
    others = [u for u in selection.units if u["section"] == "other-target-documentation"]
    assert [o["document"]["title"] for o in others] == ["new-other-target"]
    assert "text" not in others[0]
    assert [m["aspect"]["label"] for m in selection.missing_aspects()] == ["Retry", "Timeout"]
    assert {m["status"] for m in selection.missing_aspects()} == {MISSING_TEXT}


def test_profile_grammar_per_task() -> None:
    doc = profile("support-documentation")
    data = doc.model_dump(mode="json")
    data["software"]["requires_goal"] = True
    with pytest.raises(ValueError):
        SoftwareContextProfile.model_validate(data)
    impl = profile("support-implementation").model_dump(mode="json")
    impl["software"]["requires_aspects"] = False
    with pytest.raises(ValueError):
        SoftwareContextProfile.model_validate(impl)
    impl = profile("support-implementation").model_dump(mode="json")
    impl["software"]["sections"] = impl["software"]["sections"][:-1]
    with pytest.raises(ValueError):
        SoftwareContextProfile.model_validate(impl)


def test_aspects_and_token_are_bound_into_the_digest() -> None:
    base = {
        "profile": "support-implementation",
        "profile_version": "1",
        "anchor": {"id": "urn:t:op"},
        "target": {"snapshots": ["urn:t:s1"]},
    }
    one = ContextRequest.model_validate({**base, "aspects": ["retry"]})
    two = ContextRequest.model_validate({**base, "aspects": ["timeout"]})
    three = ContextRequest.model_validate({**base, "aspects": ["retry"], "followup_token": "abc"})
    assert len({request_digest(one), request_digest(two), request_digest(three)}) == 3
    with pytest.raises(ValueError):
        ContextRequest.model_validate({**base, "aspects": ["retry", "retry"]})
    with pytest.raises(ValueError):
        ContextRequest.model_validate({**base, "question": "why?"})
