"""M07-T01: two ordinary producers reuse one cross-project identity."""

from __future__ import annotations

import os
from urllib.parse import quote

from tests.integration.m07.conftest import Batteries, CaseLoader, assert_golden, package


def test_t01_reuse_and_reviewed_golden_package(batteries: Batteries) -> None:
    async def run() -> None:
        for key in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "HF_TOKEN",
            "AZURE_OPENAI_API_KEY",
        ):
            assert key not in os.environ, "M07 no-AI acceptance requires provider variables absent"
        case, loaded = batteries.case, batteries.loaded
        unauthenticated = await case.client.post(
            "/v1/context",
            json={"profile": "graph-context", "profile_version": "1", "anchor": {"label": "Tesla"}},
        )
        assert unauthenticated.status_code == 401
        invalid_install = await case.request(
            "POST",
            "/v1/changesets",
            actor="erin",
            headers={"Idempotency-Key": "m07-reject-multiple-profile-installs"},
            json={
                "base_revision": loaded["revision"],
                "operations": [
                    {"kind": "install_profile", "profile": name} for name in ("topics", "batteries")
                ],
            },
        )
        assert invalid_install.status_code == 400, invalid_install.text
        loader = CaseLoader(case)
        invalid_id = await loader.request(
            "POST",
            "/v1/changesets",
            actor="service",
            expected=(201,),
            idempotency_key="m07-reject-unrepresentable-canonical-id",
            json_body={
                "base_revision": loaded["revision"],
                "operations": [
                    {
                        "kind": "create",
                        "scope_id": "bat-shared",
                        "record": {
                            "id": "urn:c1:instance:dev:entity/12345678-1234-5678-9234-123456789abc",
                            "types": ["urn:c1:ns:core#Entity"],
                            "properties": {
                                "http://www.w3.org/2004/02/skos/core#prefLabel": [
                                    {
                                        "lexical": "Invalid canonical fixture ID",
                                        "datatype": "http://www.w3.org/2001/XMLSchema#string",
                                    }
                                ],
                                "urn:c1:ns:core#lifecycle": [
                                    {
                                        "lexical": "active",
                                        "datatype": "http://www.w3.org/2001/XMLSchema#string",
                                    }
                                ],
                            },
                        },
                    }
                ],
            },
        )
        invalid_path = "/v1/changesets/" + quote(invalid_id["id"], safe="")
        rejected = await loader.request("POST", invalid_path + "/submit", actor="service")
        assert rejected["state"] == "rejected"
        report = await loader.request("GET", invalid_path + "/validation", actor="service")
        assert "C1-ST-004" in {item["code"] for item in report["diagnostics"]}
        assert await case.knowledge.head() == loaded["revision"]
        found = await case.request("GET", "/v1/entities", actor="dave", params={"label": "Tesla"})
        assert found.status_code == 200, found.text
        assert [item["id"] for item in found.json()["items"]] == [loaded["fixture"]["ids"]["tesla"]]
        result = await package(case, loaded)
        assert result["outcome"] == "resolved"
        assert {unit["node_label"] for unit in result["structured"]["facts"]} == {
            "O-B1",
            "V-B2",
            "M-B3",
        }
        assert result["structured"]["text"] and result["structured"]["sources"]
        assert_golden(
            "context-dave.md", result["markdown"], loaded["revision"], loaded["principals"]
        )
        assert_golden(
            "context-dave.json", result["structured"], loaded["revision"], loaded["principals"]
        )

    batteries.runner.run(run())
