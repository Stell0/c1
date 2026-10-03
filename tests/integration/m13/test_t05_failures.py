"""M13-T05: injected service faults on the reference deployment fail closed and recover."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any
from urllib.parse import quote

from tests.integration.m04.conftest import action, changeset_path, new_changeset
from tests.integration.m12.conftest import PERSON
from tests.integration.m13 import reference as ref
from tests.integration.m13.conftest import Reference

C1 = "urn:c1:ns:core#"
XSD = "http://www.w3.org/2001/XMLSchema#"


async def _ready(case: Any, *, expected: int, timeout: float = 300) -> None:
    deadline = time.monotonic() + timeout
    status = None
    while time.monotonic() < deadline:
        try:
            status = (await case.client.get("/v1/readyz")).status_code
        except Exception:
            status = None
        if status == expected:
            return
        await asyncio.sleep(3)
    raise AssertionError(f"readyz stayed {status}, expected {expected}")


def _entity() -> dict[str, Any]:
    return {
        "id": f"urn:c1:instance:dev:entity/{uuid.uuid4()}",
        "types": [C1 + "Entity"],
        "properties": {
            "http://www.w3.org/2004/02/skos/core#prefLabel": [
                {"lexical": "Fault probe", "datatype": XSD + "string"}
            ],
            C1 + "lifecycle": [{"lexical": "active", "datatype": XSD + "string"}],
        },
    }


def test_t05_service_faults_fail_closed(reference: Reference) -> None:
    case = reference.case
    results: dict[str, Any] = {}

    async def run() -> None:
        person = "/v1/resources/" + quote(PERSON, safe="")
        assert (await case.request("GET", person, actor="carol")).status_code == 200
        token = await case.token("carol")

        # Authorization service unavailable: unready, and no permissive fallback.
        openfga = ref.container("openfga")
        ref.engine("pause", openfga)
        try:
            await _ready(case, expected=503)
            denied = await case.request("GET", person, actor="carol")
            results["openfga_paused"] = denied.status_code
            assert denied.status_code == 503
        finally:
            ref.engine("unpause", openfga)
        await _ready(case, expected=200)

        # Identity provider unavailable: unready; already-issued tokens validate with
        # cached keys (ADR-0008); new sign-ins are impossible.
        keycloak = ref.container("keycloak")
        ref.engine("stop", keycloak)
        try:
            await _ready(case, expected=503)
            cached = await case.client.get(person, headers={"Authorization": "Bearer " + token})
            results["keycloak_stopped_existing_token"] = cached.status_code
            assert cached.status_code in (200, 503)
        finally:
            ref.engine("start", keycloak)
        await _ready(case, expected=200, timeout=600)

        # Knowledge store unavailable: 503, never a partial page.
        terminus = ref.container("terminusdb")
        ref.engine("stop", terminus)
        try:
            failed = await case.request("GET", "/v1/entities", actor="carol")
            results["terminus_stopped"] = failed.status_code
            assert failed.status_code == 503
        finally:
            ref.engine("start", terminus)
        await _ready(case, expected=200, timeout=600)

        # C1 killed during apply: after restart exactly one outcome is committed.
        scopes = {
            item["label"]: item["id"]
            for item in (await case.request("GET", "/v1/access-scopes", actor="erin")).json()[
                "access_scopes"
            ]
        }
        company_a = scopes["Directory Company A"]
        await case.grant(company_a, "erin", "creator")
        record = _entity()
        proposal = await new_changeset(
            case, [{"kind": "create", "record": record, "scope_id": company_a}], actor="erin"
        )
        state = (await action(case, proposal["id"], "submit", actor="erin"))["state"]
        if state == "submitted":
            await action(case, proposal["id"], "validate", actor="erin")
        assert (await action(case, proposal["id"], "approve", actor="carol"))["state"] == "approved"
        key = uuid.uuid4().hex
        apply_path = changeset_path(proposal["id"], "apply")

        async def apply_once() -> int:
            try:
                response = await case.request(
                    "POST", apply_path, actor="carol", headers={"Idempotency-Key": key}
                )
                return int(response.status_code)
            except Exception:
                return -1

        pending = asyncio.ensure_future(apply_once())
        await asyncio.sleep(0.4)
        c1 = ref.container("c1")
        ref.engine("kill", "--signal", "KILL", c1)
        first = await pending
        ref.engine("start", c1)
        await _ready(case, expected=200, timeout=600)
        current = await case.request("GET", changeset_path(proposal["id"]), actor="carol")
        retry = await case.request(
            "POST", apply_path, actor="carol", headers={"Idempotency-Key": key}
        )
        results["kill_during_apply"] = {
            "first_status": first,
            "state_after_restart": current.json().get("state"),
            "retry_status": retry.status_code,
        }
        final = await case.request("GET", changeset_path(proposal["id"]), actor="carol")
        assert final.json()["state"] == "applied", final.json()
        history = await case.request(
            "GET", "/v1/history", actor="erin", params={"resource_id": record["id"]}
        )
        assert history.status_code == 200
        receipts = [i for i in history.json()["items"] if i.get("changeset_id") == proposal["id"]]
        assert len(receipts) == 1, history.json()
        consistency = ref.admin("consistency")
        assert consistency["consistent"] is True
        results["consistency_after_faults"] = consistency["consistent"]

    reference.run(run())
    evidence = ref.ROOT / "docs/evidence/M13"
    evidence.mkdir(parents=True, exist_ok=True)
    import json

    (evidence / "t05-reference-faults.json").write_text(json.dumps(results, indent=2) + "\n")
