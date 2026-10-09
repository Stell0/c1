"""M03-D1: settings are startup-owned and secrets stay out of repr."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from c1.authorization.principal import Principal
from c1.config import Settings


def settings() -> Settings:
    return Settings(
        instance_id="dev",
        instance_base="urn:c1:instance:dev:",
        issuer="http://127.0.0.1:18090/realms/c1-dev",
        issuer_alias="c1-dev",
        audience="c1-api",
        fga_url="http://127.0.0.1:18080",
        fga_token="secret-fga-token",
        fga_store="store-id",
        fga_model="model-id",
        terminus_url="http://127.0.0.1:16363",
        terminus_password="secret-terminus-password",
        organization="admin",
        knowledge_database="c1_m03_knowledge",
        workflow_database="c1_m03_workflow",
        lock_path=Path("/tmp/c1-m03-test.lock"),
    )


def test_explicit_settings_are_frozen_and_redacted() -> None:
    configured = settings()
    assert "secret-fga-token" not in repr(configured)
    assert "secret-terminus-password" not in repr(configured)
    assert configured.independent_review
    assert not configured.enable_probe_routes
    with pytest.raises(AttributeError):
        configured.audience = "other"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("issuer", "http://user:pass@127.0.0.1/realms/test"),
        ("fga_url", "https://example.invalid/path"),
        ("terminus_url", "http://127.0.0.1:16363/?database=other"),
        ("issuer_alias", "other.realm"),
        ("knowledge_database", "../other"),
        ("lock_path", Path("relative.lock")),
    ],
)
def test_invalid_deployment_routing_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        replace(settings(), **{field: value})  # type: ignore[arg-type]


def test_from_env_reads_only_startup_owned_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    configured = settings()
    values = {
        "C1_ISSUER": configured.issuer,
        "C1_FGA_TOKEN": configured.fga_token,
        "C1_CURSOR_SECRET": "synthetic-test-cursor-key-" * 2,  # pragma: allowlist secret
        "C1_FGA_STORE": configured.fga_store,
        "C1_FGA_MODEL": configured.fga_model,
        "C1_TERMINUS_PASSWORD": configured.terminus_password,
        "C1_KNOWLEDGE_DATABASE": configured.knowledge_database,
        "C1_WORKFLOW_DATABASE": configured.workflow_database,
        "C1_ENABLE_PROBE_ROUTES": "false",
        "C1_INDEPENDENT_REVIEW": "true",
        "C1_REQUEST_DATABASE": "other",
        "C1_REQUEST_PRINCIPAL": "admin",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    loaded = Settings.from_env()
    assert loaded.knowledge_database == configured.knowledge_database
    assert loaded.issuer_alias == "c1-dev"
    assert loaded.independent_review
    assert not loaded.enable_probe_routes
    monkeypatch.setenv("C1_ENABLE_PROBE_ROUTES", "sometimes")
    with pytest.raises(ValueError, match="C1_ENABLE_PROBE_ROUTES"):
        Settings.from_env()


def test_principal_encoding_is_injective_and_safe() -> None:
    first = Principal("issuer-one", "a.b", "human")
    second = Principal("issuer-one", "a-b", "service")
    third = Principal("issuer-two", "a.b", "human")
    assert first.id == "user:issuer-one.a.b"
    assert len({first.id, second.id, third.id}) == 3
    with pytest.raises(ValueError):
        Principal("issuer.one", "abc", "human")
    with pytest.raises(ValueError):
        Principal("issuer-one", "abc\nreader", "human")
