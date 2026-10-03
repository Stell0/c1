"""M13-T04: a full restore serves nothing until security freshness is verified and released."""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import pytest

from tests.integration.m12.conftest import PERSON
from tests.integration.m13 import reference as ref
from tests.integration.m13.conftest import Reference

DR = "c1-dr"
DR_PREFIX = "10.89.252"
DR_BASE = "https://c1.test:18444"
DR_AUTH = "https://auth.c1.test:18444/realms/c1"

_PROBE = """
import json, urllib.request, urllib.error
out = {}
for path in ("/v1/readyz", "/v1/instance", "/v1/entities"):
    request = urllib.request.Request("http://127.0.0.1:8000" + path,
                                     headers={"Authorization": "Bearer a.b.c"})
    try:
        out[path] = urllib.request.urlopen(request, timeout=10).status
    except urllib.error.HTTPError as error:
        out[path] = error.code
print(json.dumps(out))
"""

_FGA = """
import json, os, sys, urllib.request
token = open("/run/c1/secrets/fga_token").read().strip()
base = os.environ["C1_FGA_URL"] + "/stores/" + os.environ["C1_FGA_STORE"]
def call(path, body):
    request = urllib.request.Request(base + path, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=30).read() or b"{}")
mode, payload = sys.argv[1], sys.argv[2]
if mode == "take":
    tuples = call("/read", {"page_size": 100})["tuples"]
    key = next(t["key"] for t in tuples if t["key"]["relation"] == "bound_to")
    call("/write", {"deletes": {"tuple_keys": [key]},
                    "authorization_model_id": os.environ["C1_FGA_MODEL"]})
    print(json.dumps(key))
else:
    call("/write", {"writes": {"tuple_keys": [json.loads(payload)]},
                    "authorization_model_id": os.environ["C1_FGA_MODEL"]})
    print("{}")
"""


def _in_dr(script: str, *args: str) -> str:
    return ref.engine(
        "exec", "--user", "10001", ref.container("c1", DR), "python", "-c", script, *args
    )


def _dr_admin(*argv: str, target: Path) -> dict[str, object]:
    return ref.admin(*argv, "--net-prefix", DR_PREFIX, directory=target, project=DR)


def test_t04_guarded_disaster_recovery(reference: Reference) -> None:
    case = reference.case
    work = Path(tempfile.mkdtemp(prefix="c1-m13-t04-"))
    target = work / "dr"

    async def run() -> None:
        ref.admin("backup", "--to", str(work / "full"))
        scopes = {
            item["label"]: item["id"]
            for item in (await case.request("GET", "/v1/access-scopes", actor="erin")).json()[
                "access_scopes"
            ]
        }
        shared = scopes["Directory shared contacts"]
        alice = (await case.principal("alice")).id
        revoked = await case.request(
            "DELETE",
            f"/v1/access-scopes/{quote(shared, safe='')}/members/{quote(alice, safe='')}",
            actor="erin",
            params={"role": "reader"},
        )
        assert revoked.status_code == 200, revoked.text
        person = await case.request("GET", "/v1/resources/" + quote(PERSON, safe=""), actor="alice")
        assert person.status_code == 404

        restored = ref.admin(
            "restore-full",
            "--from",
            str(work / "full"),
            "--target-dir",
            str(target),
            "--target-project",
            DR,
            "--target-net-prefix",
            DR_PREFIX,
            "--target-port",
            "18444",
        )
        assert restored["guard"]
        # Guarded: nothing is served, and no port is published before release.
        assert json.loads(_in_dr(_PROBE)) == {
            "/v1/readyz": 503,
            "/v1/instance": 503,
            "/v1/entities": 503,
        }
        published = ref.engine(
            "ps", "--filter", f"label=com.docker.compose.project={DR}", "--format", "{{.Ports}}"
        )
        assert "->" not in published

        # An injected binding mismatch fails verification and blocks release.
        taken = _in_dr(_FGA, "take", "").strip()
        with pytest.raises(RuntimeError):
            _dr_admin("dr", "verify", target=target)
        accept = datetime.now(UTC).isoformat(timespec="seconds")
        with pytest.raises(RuntimeError, match="verify"):
            _dr_admin(
                "dr",
                "release",
                "--port",
                "18444",
                "--accept-security-as-of",
                accept,
                "--reason",
                "should be refused",
                target=target,
            )
        _in_dr(_FGA, "put", taken)
        verified = _dr_admin("dr", "verify", target=target)
        assert verified["consistent"] is True and verified["pending_operations"] == 0
        no_acceptance = subprocess.run(
            [
                "uv",
                "run",
                "--locked",
                "c1-admin",
                "dr",
                "release",
                "--dir",
                str(target),
                "--project",
                DR,
                "--net-prefix",
                DR_PREFIX,
                "--reason",
                "x",
            ],
            cwd=ref.ROOT,
            capture_output=True,
        )
        assert no_acceptance.returncode != 0
        released = _dr_admin(
            "dr",
            "release",
            "--port",
            "18444",
            "--accept-security-as-of",
            accept,
            "--reason",
            "M13-T04 drill",
            target=target,
        )
        assert released["accepted_security_as_of"]

        dr = ref.ReferenceCase(reference.identities, base=DR_BASE, auth=DR_AUTH)
        try:
            ready = await dr.client.get("/v1/readyz")
            assert ready.status_code == 200, ready.text
            # The restored security state is the backup's: Alice's later revocation is
            # not in it. The operator re-applies it before traffic, as documented.
            back = await dr.request("GET", "/v1/resources/" + quote(PERSON, safe=""), actor="alice")
            assert back.status_code == 200
            again = await dr.request(
                "DELETE",
                f"/v1/access-scopes/{quote(shared, safe='')}/members/{quote(alice, safe='')}",
                actor="erin",
                params={"role": "reader"},
            )
            assert again.status_code == 200, again.text
            gone = await dr.request("GET", "/v1/resources/" + quote(PERSON, safe=""), actor="alice")
            assert gone.status_code == 404
        finally:
            await dr.close()

    try:
        reference.run(run())
    finally:
        ref.teardown(target, DR)
        subprocess.run(["rm", "-rf", str(work)], check=False)
