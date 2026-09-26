"""Durable, fail-closed publication experiment; not a product authorization API."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from probes.config import ROOT, Settings
from probes.fga import FGA, FGAError
from probes.terminus import BackendError, Terminus
from probes.writer import ProbeWriter

_LOCKS: dict[str, asyncio.Lock] = {}


@asynccontextmanager
async def publication_lock(repository: str) -> AsyncIterator[None]:
    """One local writer across restart processes; reads use the same gate lock."""
    lock = _LOCKS.setdefault(repository, asyncio.Lock())
    async with lock:
        directory = ROOT / "deployment/.state"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / (hashlib.sha256(repository.encode()).hexdigest() + ".lock")
        with path.open("a") as stream:
            await asyncio.to_thread(fcntl.flock, stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def journal_id(resource: str) -> str:
    return "Publication/" + hashlib.sha256(resource.encode()).hexdigest()


def crash_after(point: str) -> None:
    if os.environ.get("C1_PROBE_CRASH_AFTER") == point:
        os._exit(86)


class Publisher:
    def __init__(self, knowledge: Terminus, workflow: Terminus, fga: FGA) -> None:
        self.knowledge = knowledge
        self.workflow = workflow
        self.fga = fga
        self.writer = ProbeWriter(knowledge, workflow)
        self.journal_ms: list[float] = []

    async def save(self, record: dict[str, Any], new: bool = False) -> None:
        started = time.perf_counter()
        method = self.workflow.insert if new else self.workflow.replace
        await method([record], "M01 publication journal", await self.workflow.head())
        self.journal_ms.append((time.perf_counter() - started) * 1000)

    async def publish(self, document: dict[str, Any], scope: str) -> None:
        resource = str(document["@id"])
        async with publication_lock(self.knowledge.database):
            if await self.workflow.get(journal_id(resource)) is not None:
                raise ValueError("Publication already exists; use reconciliation")
            record = {
                "@id": journal_id(resource),
                "@type": "Publication",
                "resource_id": resource,
                "scope_id": scope,
                "state": "pending",
                "payload": json.dumps(document, sort_keys=True),
                "base_revision": await self.knowledge.head(),
                "knowledge_commit": "",
            }
            await self.save(record, new=True)
            crash_after("journal")
            await self._reconcile(record)

    async def reconcile(self, resource: str) -> None:
        async with publication_lock(self.knowledge.database):
            record = await self.workflow.get(journal_id(resource))
            if record is None:
                raise ValueError("Missing publication journal")
            await self._reconcile(record)

    async def _reconcile(self, record: dict[str, Any]) -> None:
        if record["state"] in {"complete", "failed"}:
            return
        resource = record["resource_id"]
        try:
            document = json.loads(record["payload"])
            if document.get("@id") != resource:
                raise ValueError("Journal resource does not match payload")
            commit = await self.writer.apply(
                journal_id(resource), [document], record["base_revision"]
            )
            crash_after("content")
            record.update(state="content_written", knowledge_commit=commit)
            await self.save(record)
            await self.fga.bind("resource:" + resource, record["scope_id"])
            crash_after("binding")
            record["state"] = "binding_written"
            await self.save(record)
            if await self.fga.bindings("resource:" + resource) != [record["scope_id"]]:
                raise FGAError("Binding was not confirmed")
            if await self.knowledge.get(resource, commit) is None:
                raise ValueError("Committed content is absent")
            record["state"] = "complete"
            await self.save(record)
        except (BackendError, ValueError):
            # A durable failed journal is the deny tombstone. The prototype model
            # has no deny tuple; do not invent one or fall back to old bindings.
            record["state"] = "failed"
            await self.save(record)
            current = await self.fga.bindings("resource:" + resource)
            await self.fga.write(
                [], [(scope, "bound_to", "resource:" + resource) for scope in current]
            )
            raise
        # Transport/FGA outages leave the durable non-complete state for retry.

    async def read(
        self, resource: str, user: str, commit: str | None = None
    ) -> dict[str, Any] | None:
        try:
            async with publication_lock(self.knowledge.database):
                record = await self.workflow.get(journal_id(resource))
                if record is None or record.get("state") != "complete":
                    return None
                if await self.fga.bindings("resource:" + resource) != [record["scope_id"]]:
                    return None
                if not await self.fga.check(user, "reader", "resource:" + resource):
                    return None
                return await self.knowledge.get(resource, commit)
        except Exception:
            # Includes unavailable/missing workflow, FGA, or content services.
            return None


async def run_cli(args: argparse.Namespace) -> None:
    settings = Settings.load()
    async with (
        Terminus(settings.terminus_url, settings.terminus_password, args.knowledge) as knowledge,
        Terminus(settings.terminus_url, settings.terminus_password, args.workflow) as workflow,
        FGA(settings.fga_url, settings.fga_token, args.store, args.model) as fga,
    ):
        publisher = Publisher(knowledge, workflow, fga)
        if args.action == "publish":
            await publisher.publish(
                {
                    "@type": "Item",
                    "@id": args.resource,
                    "name": "Synthetic publication",
                    "value": 1,
                },
                args.scope,
            )
        else:
            await publisher.reconcile(args.resource)
        print(json.dumps({"journal_write_ms": publisher.journal_ms}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["publish", "reconcile"])
    for name in ("knowledge", "workflow", "store", "model", "resource"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--scope", default="scope:shared")
    asyncio.run(run_cli(parser.parse_args()))


if __name__ == "__main__":
    main()
