"""M13-T08: packaging, secrets, AI-freedom and license records of the candidate."""

from __future__ import annotations

import json
import subprocess

from tests.integration.m13 import reference as ref
from tests.integration.m13.conftest import Reference


def test_t08_release_audit_and_license_inventory(reference: Reference) -> None:
    assert reference.bootstrap["first_admin_principal"]
    out = ref.ROOT / "docs/evidence/M13/release-audit.json"
    audit = subprocess.run(
        ["uv", "run", "--locked", "python", "scripts/release_audit.py", "--out", str(out)],
        cwd=ref.ROOT,
        capture_output=True,
    )
    report = json.loads(out.read_text())
    assert audit.returncode == 0, report["findings"]
    assert report["deployment"]["running"] is True
    assert list(report["deployment"]["published"]) == [ref.container("proxy")]
    licenses = subprocess.run(
        ["uv", "run", "--locked", "python", "scripts/license_inventory.py", "--check"],
        cwd=ref.ROOT,
        capture_output=True,
    )
    assert licenses.returncode == 0, licenses.stderr.decode()[-800:]
