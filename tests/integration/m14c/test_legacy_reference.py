"""A pre-M14c reference layout keeps its principal grants during upgrade."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from c1.api.app import create_app
from c1.runtime import Runtime
from tests.integration.m03.conftest import entity_record, live_case, resource_path


@pytest.mark.integration
def test_t14_legacy_reference_without_identity_metadata(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)

    async def run() -> None:
        async with live_case() as legacy:
            scope = await legacy.scope("Legacy reference scope")
            await legacy.grant(scope, "alice", "reader")
            record = entity_record(label="Preserved legacy identity")
            await legacy.provision(record, scope)
            token = await legacy.token("alice")
            assert await legacy.journal.get("Restore", "application-identity") is None
            # An upgrade quiesces the original writer; opening two owners of
            # the same writer lock correctly prevents readiness.
            await legacy.runtime.close()
            settings = replace(
                legacy.settings, initialization_file=tmp_path / "missing-legacy-initialization.json"
            )
            runtime = Runtime(settings)
            app = create_app(settings, runtime=runtime)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://c1.test"
                ) as client:
                    assert (await client.get("/v1/readyz")).status_code == 200
                    read = await client.get(
                        resource_path(record.id), headers={"Authorization": "Bearer " + token}
                    )
                    assert read.status_code == 200 and "Preserved legacy identity" in read.text
                    assert settings.initialization_file is not None
                    assert not settings.initialization_file.exists()

    asyncio.run(run())
