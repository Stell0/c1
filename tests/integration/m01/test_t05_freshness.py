"""M01-T05: current policy controls history, including real service faults."""

from __future__ import annotations

import asyncio
import subprocess
import time

from probes.config import runtime
from probes.publication import Publisher, journal_id
from probes.session import session
from scripts.stack import container_id, wait_ready


def test_t05_current_bindings_and_revocation() -> None:
    async def scenario() -> None:
        async with session() as services:
            publisher = Publisher(services.knowledge, services.workflow, services.fga)
            fga = services.fga
            resource = "Item/protected"
            grant = ("group:g#member", "reader", "scope:shared")
            await fga.write([("user:u", "member", "group:g"), grant])
            await publisher.publish(
                {
                    "@type": "Item",
                    "@id": resource,
                    "name": "old",
                    "value": 1,
                    "access_scope_id": "scope:shared",
                },
                "scope:shared",
            )
            old = await services.knowledge.head()
            assert await publisher.read(resource, "user:u", old) is not None
            await fga.bind("resource:" + resource, "scope:restricted")
            assert not await fga.check("user:u", "reader", "resource:" + resource)
            assert await publisher.read(resource, "user:u", old) is None
            record = await services.workflow.get(journal_id(resource))
            assert record is not None
            record["scope_id"] = "scope:restricted"
            await publisher.save(record)
            assert await publisher.read(resource, "user:u", old) is None
            # An extra stale shared binding must not broaden the read gate.
            await fga.write([("scope:shared", "bound_to", "resource:" + resource)])
            assert await fga.check("user:u", "reader", "resource:" + resource)
            assert await publisher.read(resource, "user:u", old) is None
            await fga.bind("resource:" + resource, "scope:shared")
            record["scope_id"] = "scope:shared"
            await publisher.save(record)
            await fga.write([], [grant])
            assert not await fga.check("user:u", "reader", "resource:" + resource)
            assert await publisher.read(resource, "user:u", old) is None
            await fga.write([grant])
            assert await publisher.read(resource, "user:u", old) is not None
            await fga.write([], [("scope:shared", "bound_to", "resource:" + resource)])
            assert await publisher.read(resource, "user:u", old) is None
            assert await publisher.read("Item/missing", "user:u") is None

    asyncio.run(scenario())


def test_t05_live_outage_and_timeout() -> None:
    async def scenario() -> None:
        async with session() as services:
            publisher = Publisher(services.knowledge, services.workflow, services.fga)
            resource = "Item/outage"
            await services.fga.write([("user:u", "reader", "scope:shared")])
            await publisher.publish(
                {"@type": "Item", "@id": resource, "name": "outage", "value": 1},
                "scope:shared",
            )
            assert await publisher.read(resource, "user:u") is not None
            container = container_id("openfga")
            for fault, recovery in [("pause", "unpause"), ("kill", "start")]:
                subprocess.run([runtime(), fault, container], check=True, capture_output=True)
                try:
                    started = time.monotonic()
                    async with asyncio.timeout(20):
                        assert await publisher.read(resource, "user:u") is None
                        assert not await services.fga.check(
                            "user:u", "reader", "resource:" + resource
                        )
                    assert time.monotonic() - started < 20
                finally:
                    subprocess.run(
                        [runtime(), recovery, container], check=True, capture_output=True
                    )
                    await asyncio.to_thread(wait_ready)
                assert await publisher.read(resource, "user:u") is not None

    asyncio.run(scenario())
