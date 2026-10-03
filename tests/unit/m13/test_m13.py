"""M13 unit checks: secret files, restore guard, manifests, OpenAPI parity, wheel, licenses."""

from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from c1.admin.host import HostError, _sha256, load_manifest
from c1.config import secret_value
from c1.runtime import restore_guarded

ROOT = Path(__file__).resolve().parents[3]


def _secret(tmp_path: Path, mode: int, text: str = "s3cret-value\n") -> Path:
    path = tmp_path / "value"
    path.write_text(text)
    path.chmod(mode)
    return path


def test_secret_files_precedence_permissions_and_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "C1_FGA_TOKEN"
    monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(name + "_FILE", raising=False)
    assert secret_value(name) is None
    monkeypatch.setenv(name, "direct")
    assert secret_value(name) == "direct"
    good = _secret(tmp_path, 0o400)
    monkeypatch.setenv(name + "_FILE", str(good))
    with pytest.raises(ValueError, match="not both"):
        secret_value(name)
    monkeypatch.delenv(name)
    assert secret_value(name) == "s3cret-value"
    good.chmod(0o440)
    assert secret_value(name) == "s3cret-value"
    for mode in (0o444, 0o600, 0o640):
        good.chmod(mode)
        with pytest.raises(ValueError, match="mode") as error:
            secret_value(name)
        assert "s3cret" not in str(error.value)
    good.chmod(0o400)
    link = tmp_path / "link"
    link.symlink_to(good)
    monkeypatch.setenv(name + "_FILE", str(link))
    with pytest.raises(ValueError, match="symlink"):
        secret_value(name)
    monkeypatch.setenv(name + "_FILE", "relative/path")
    with pytest.raises(ValueError, match="absolute"):
        secret_value(name)
    two = tmp_path / "two"
    two.write_text("a\nb\n")
    two.chmod(0o400)
    monkeypatch.setenv(name + "_FILE", str(two))
    with pytest.raises(ValueError, match="one non-empty line"):
        secret_value(name)


def test_restore_guard_semantics() -> None:
    assert restore_guarded([]) is False
    assert restore_guarded([{"type": "knowledge"}]) is False
    assert restore_guarded([{"type": "guard", "released": False}]) is True
    assert restore_guarded([{"type": "guard"}]) is True
    assert restore_guarded([{"type": "guard", "released": "yes"}]) is True
    assert restore_guarded([{"type": "guard", "released": True}]) is False


def test_guarded_runtime_answers_503_for_every_protected_request(tmp_path: Path) -> None:
    import asyncio
    from typing import Any, cast

    import httpx

    from c1.api import create_app
    from scripts.openapi import _settings
    from tests.unit.m12.test_api_additions import _Runtime

    fake = _Runtime(_settings())
    fake.guarded = True  # type: ignore[attr-defined]

    async def run() -> None:
        app = create_app(_settings(), runtime=cast(Any, fake))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for path in ("/v1/instance", "/v1/entities", "/v1/schema"):
                response = await client.get(path, headers={"Authorization": "Bearer good"})
                assert response.status_code == 503
            assert "request_boundary" in fake.events

    asyncio.run(run())


def test_manifest_validation_refuses_incomplete_or_altered_backups(tmp_path: Path) -> None:
    with pytest.raises(HostError, match="incomplete"):
        load_manifest(tmp_path)
    data = tmp_path / "terminusdb-storage.tar"
    data.write_bytes(b"storage")
    manifest = {"manifest_version": 1, "files": {data.name: _sha256(data)}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    assert load_manifest(tmp_path)["files"]
    data.write_bytes(b"tampered")
    with pytest.raises(HostError, match="altered"):
        load_manifest(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({**manifest, "manifest_version": 9}))
    with pytest.raises(HostError, match="version"):
        load_manifest(tmp_path)


def test_openapi_document_matches_the_implemented_routes() -> None:
    from scripts import openapi

    document = json.loads((ROOT / "docs/api/openapi.json").read_text())
    assert openapi.documented_routes(document) == openapi.implemented_routes(openapi.application())
    assert (
        json.dumps(openapi.build(), indent=2, sort_keys=True) + "\n"
        == (ROOT / "docs/api/openapi.json").read_text()
    )
    readyz = document["paths"]["/v1/readyz"]["get"]
    assert "security" not in readyz
    assert document["paths"]["/v1/instance"]["get"]["security"] == [{"bearer": []}]


def test_wheel_contains_runtime_data(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "-o", str(tmp_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        env={**os.environ, "UV_OFFLINE": "1"},
    )
    names = set(zipfile.ZipFile(next(tmp_path.glob("*.whl"))).namelist())
    for required in (
        "c1/explorer/templates/base.html",
        "c1/explorer/static/explorer.css",
        "c1/admin/realm-c1.json",
        "c1/profiles/core/profile.json",
        "c1/profiles/available/software/profile.json",
        "c1/profiles/context/documentation-update.json",
        "c1/authorization/c1-v1.json",
    ):
        assert required in names, required
    assert not any(name.startswith(("tests/", "fixtures/")) for name in names)


def test_license_inventory_is_current_and_allowed() -> None:
    from scripts import license_inventory

    serial, text = license_inventory.build()
    assert license_inventory.policy(serial) == []
    assert (ROOT / "THIRD_PARTY_NOTICES").read_text() == text
    names = {entry["name"].lower() for entry in serial["python"]}
    assert {"fastapi", "jinja2", "pyjwt"} <= names
    assert not names & {"openai", "anthropic", "torch", "transformers", "playwright", "pytest"}


def test_realm_template_has_no_credentials() -> None:
    text = (ROOT / "src/c1/admin/realm-c1.json").read_text()
    realm = json.loads(text)
    explorer = next(c for c in realm["clients"] if c["clientId"] == "c1-explorer")
    assert explorer["secret"] == "@EXPLORER_CLIENT_SECRET@"
    assert "users" not in realm
    assert all(not c.get("directAccessGrantsEnabled") for c in realm["clients"])
