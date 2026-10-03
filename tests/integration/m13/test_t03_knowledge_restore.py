"""M13-T03: a knowledge-only restore never reinstates old grants or bindings."""

from __future__ import annotations

import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest

from tests.integration.m04.conftest import action, changeset_path, new_changeset
from tests.integration.m13 import reference as ref
from tests.integration.m13.conftest import Reference

COMPANY_A_NOTE = "urn:c1:instance:dev:assertion/00000024-0000-4000-8000-000000000000"
DOCUMENT = "urn:c1:instance:dev:document/00000061-0000-4000-8000-000000000000"
C1 = "urn:c1:ns:core#"
XSD = "http://www.w3.org/2001/XMLSchema#"


def _entity(label: str) -> dict[str, object]:
    return {
        "id": f"urn:c1:instance:dev:entity/{uuid.uuid4()}",
        "types": [C1 + "Entity"],
        "properties": {
            "http://www.w3.org/2004/02/skos/core#prefLabel": [
                {"lexical": label, "datatype": XSD + "string"}
            ],
            C1 + "lifecycle": [{"lexical": "active", "datatype": XSD + "string"}],
        },
    }


def test_t03_knowledge_only_restore_keeps_current_security(reference: Reference) -> None:
    case = reference.case
    backups = Path(tempfile.mkdtemp(prefix="c1-m13-t03-"))

    async def scope_ids() -> dict[str, str]:
        response = await case.request("GET", "/v1/access-scopes", actor="erin")
        return {item["label"]: item["id"] for item in response.json()["access_scopes"]}

    async def apply(operations: list[dict[str, object]]) -> str:
        proposal = await new_changeset(case, operations, actor="erin")
        state = (await action(case, proposal["id"], "submit", actor="erin"))["state"]
        if state == "submitted":
            await action(case, proposal["id"], "validate", actor="erin")
        assert (await action(case, proposal["id"], "approve", actor="carol"))["state"] == "approved"
        assert (await action(case, proposal["id"], "apply", actor="carol"))["state"] == "applied"
        return str(proposal["id"])

    async def run() -> None:
        before = await case.knowledge.head()
        backup = ref.admin("backup", "--to", str(backups / "k1"), "--knowledge-only")
        assert backup["sizes"]["terminusdb-storage.tar"] > 0
        scopes = await scope_ids()
        company_a, team = (
            scopes["Directory Company A"],
            next(v for k, v in scopes.items() if k.startswith("M06 Handbook team")),
        )
        # Tighten security after the backup.
        restricted = await case.scope("M13 restricted notes")
        for scope in (restricted, company_a):
            await case.grant(scope, "frank", "access_admin")
        proposed = await case.request(
            "POST",
            f"/v1/access-scopes/{quote(restricted, safe='')}/bindings",
            actor="erin",
            json={"resource_id": COMPANY_A_NOTE},
        )
        assert proposed.status_code in (200, 201), proposed.text
        operation = proposed.json()["id"]
        for step, actor in (("approve", "frank"), ("apply", "erin")):
            response = await case.request(
                "POST", f"/v1/security-operations/{quote(operation, safe='')}/{step}", actor=actor
            )
            assert response.status_code == 200, response.text
        bob = (await case.principal("bob")).id
        revoked = await case.request(
            "DELETE",
            f"/v1/access-scopes/{quote(team, safe='')}/members/{quote(bob, safe='')}",
            actor="erin",
            params={"role": "reader"},
        )
        assert revoked.status_code == 200, revoked.text
        # A resource created after the backup keeps its binding but loses its record.
        later = _entity("Created after the backup")
        await case.grant(company_a, "erin", "creator")
        await apply([{"kind": "create", "record": later, "scope_id": company_a}])
        # A draft prepared on the post-backup head becomes stale after the restore.
        stale = await new_changeset(
            case,
            [{"kind": "create", "record": _entity("Stale draft"), "scope_id": company_a}],
            actor="erin",
        )
        alice_note_before = await case.request(
            "GET", "/v1/resources/" + quote(COMPANY_A_NOTE, safe=""), actor="alice"
        )
        assert alice_note_before.status_code == 404  # already re-scoped away from Alice

        restored = ref.admin("restore-knowledge", "--from", str(backups / "k1"))
        assert restored["restored_head"] == before == backup_head(backups / "k1")
        assert await case.knowledge.head() == before

        # Current security still governs the restored knowledge.
        for actor in ("alice", "carol"):
            note = await case.request(
                "GET", "/v1/resources/" + quote(COMPANY_A_NOTE, safe=""), actor=actor
            )
            history = await case.request(
                "GET", "/v1/history", actor=actor, params={"resource_id": COMPANY_A_NOTE}
            )
            assert note.status_code == 404 and history.status_code == 404, actor
            export = await case.request("GET", "/v1/export", actor=actor, params={"limit": 200})
            assert COMPANY_A_NOTE not in export.text
        bob_view = await case.request(
            "GET",
            f"/v1/documents/{quote(DOCUMENT, safe='')}/render",
            actor="bob",
            params={"format": "markdown"},
        )
        alice_view = await case.request(
            "GET",
            f"/v1/documents/{quote(DOCUMENT, safe='')}/render",
            actor="alice",
            params={"format": "markdown"},
        )
        assert bob_view.json()["content"] == alice_view.json()["content"]  # team part gone
        missing = await case.request(
            "GET", "/v1/resources/" + quote(str(later["id"]), safe=""), actor="erin"
        )
        assert missing.status_code == 404
        state = ref.admin_internal_state()
        assert any(r["type"] == "knowledge" for r in state["restore_records"])
        # The pre-restore draft is on a head that no longer exists: refused, not applied.
        submitted = await case.request("POST", changeset_path(stale["id"], "submit"), actor="erin")
        assert submitted.status_code in (200, 409), submitted.text
        if submitted.status_code == 200:
            assert submitted.json()["state"] in {"stale", "rejected"}, submitted.json()["state"]
        # A new ChangeSet on the restored head applies.
        await apply([{"kind": "create", "record": _entity("After restore"), "scope_id": company_a}])

        # A backup without a profile installed later is refused before any change.
        install = await new_changeset(
            case, [{"kind": "install_profile", "profile": "example-vehicle"}], actor="erin"
        )
        state_now = (await action(case, install["id"], "submit", actor="erin"))["state"]
        if state_now == "submitted":
            await action(case, install["id"], "validate", actor="erin")
        await action(case, install["id"], "approve", actor="carol")
        await action(case, install["id"], "apply", actor="carol")
        head = await case.knowledge.head()
        with pytest.raises(RuntimeError, match="profiles installed after the backup"):
            ref.admin("restore-knowledge", "--from", str(backups / "k1"))
        assert await case.knowledge.head() == head

    try:
        reference.run(run())
    finally:
        subprocess.run(["rm", "-rf", str(backups)], check=False)


def backup_head(directory: Path) -> str:
    import json

    return str(json.loads((directory / "manifest.json").read_text())["knowledge_head"])
