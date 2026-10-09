"""Protected approvals, namespace continuity, and dynamic setup guards."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from c1.admin.initialization import (
    InitializationError,
    approve,
    cancel,
    checked,
    guarded,
    identity,
    load,
    save,
)
from c1.authorization.principal import Principal
from c1.config import Settings
from c1.runtime import Runtime
from tests.unit.m03.test_tokens import _settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    tmp_path.chmod(0o700)
    result = replace(
        _settings("http://127.0.0.1:29090"),
        identity_mode="external",
        initialization_file=tmp_path / "initialization.json",
        lock_path=tmp_path / "writer",
    )
    save(
        tmp_path / "initialization.json",
        {
            "contract_version": 1,
            "identity": identity(result),
            "state": "awaiting_enrollment",
            "fga_store": result.fga_store,
            "fga_model": result.fga_model,
        },
    )
    return result


def test_approval_cancellation_and_exact_identity(settings: Settings) -> None:
    assert guarded(settings)
    approve(settings, settings.issuer, "opaque|subject", "test-operator", 3600)
    state = checked(settings)
    assert state and state["approval"]["subject"] == "opaque|subject"

    async def check() -> None:
        runtime = Runtime(settings)
        try:
            assert runtime.enrollment_pending()
            assert not await runtime.ready()
            with pytest.raises(InitializationError, match="not_approved"):
                await runtime.setup_identity(Principal(settings.issuer_alias, "wrong", "human"))
            result = await runtime.setup_identity(
                Principal(settings.issuer_alias, "opaque|subject", "human")
            )
            assert result["enrollment_pending"] is True
        finally:
            await runtime.close()

    asyncio.run(check())
    cancel(settings)
    assert "approval" not in (checked(settings) or {})
    assert guarded(settings)


def test_enrollment_cannot_reopen_or_replace_started_grants(settings: Settings) -> None:
    assert settings.initialization_file
    approve(settings, settings.issuer, "approved", "operator", 3600)
    state = load(settings.initialization_file)
    for status in ("enrolling", "complete"):
        state["state"] = status
        save(settings.initialization_file, state)
        with pytest.raises(InitializationError, match="not_available"):
            approve(settings, settings.issuer, "replacement", "operator", 3600)
        with pytest.raises(InitializationError, match="not_available"):
            cancel(settings)


def test_missing_state_and_configuration_changes_fail_closed(settings: Settings) -> None:
    for changed in (
        replace(settings, issuer_alias="other"),
        replace(settings, issuer="http://127.0.0.1:29091"),
        replace(settings, audience="other-api"),
        replace(settings, fga_store="another-store"),
    ):
        assert guarded(changed)
    assert settings.initialization_file
    settings.initialization_file.unlink()
    assert guarded(settings)


def test_complete_local_receipt_alone_cannot_enable_runtime(settings: Settings) -> None:
    assert settings.initialization_file
    state = load(settings.initialization_file)
    state["state"] = "complete"
    save(settings.initialization_file, state)

    async def check() -> None:
        runtime = Runtime(settings)
        try:
            assert runtime.enrollment_pending()
            assert not await runtime.ready()
        finally:
            await runtime.close()

    asyncio.run(check())


def test_unsafe_local_state_is_rejected(settings: Settings) -> None:
    assert settings.initialization_file
    settings.initialization_file.chmod(0o644)
    with pytest.raises(InitializationError, match="unsafe"):
        load(settings.initialization_file)
