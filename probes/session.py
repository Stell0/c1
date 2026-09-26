"""Fresh, scoped real-service fixtures for M01 integration experiments."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from probes.config import Settings
from probes.fga import FGA
from probes.terminus import Terminus


def knowledge_schema() -> list[dict[str, Any]]:
    return [
        {
            "@type": "Class",
            "@id": "Item",
            "name": "xsd:string",
            "value": "xsd:integer",
            "access_scope_id": {"@type": "Optional", "@class": "xsd:string"},
        },
    ]


def workflow_schema() -> list[dict[str, Any]]:
    return [
        {
            "@type": "Class",
            "@id": "Receipt",
            "changeset": "xsd:string",
            "digest": "xsd:string",
            "principal": "xsd:string",
            "knowledge_commit": "xsd:string",
        },
        {
            "@type": "Class",
            "@id": "Publication",
            "resource_id": "xsd:string",
            "scope_id": "xsd:string",
            "state": "xsd:string",
            "payload": "xsd:string",
            "base_revision": "xsd:string",
            "knowledge_commit": "xsd:string",
        },
    ]


@dataclass
class Session:
    knowledge: Terminus
    workflow: Terminus
    fga: FGA


@asynccontextmanager
async def session(schema: list[dict[str, Any]] | None = None) -> AsyncIterator[Session]:
    settings = Settings.load()
    suffix = uuid4().hex
    async with AsyncExitStack() as stack:
        knowledge = await stack.enter_async_context(
            Terminus(settings.terminus_url, settings.terminus_password, "c1_m01_" + suffix)
        )
        workflow = await stack.enter_async_context(
            Terminus(
                settings.terminus_url, settings.terminus_password, "c1_m01_" + suffix + "_workflow"
            )
        )
        fga = await stack.enter_async_context(FGA(settings.fga_url, settings.fga_token))
        await knowledge.create()
        stack.push_async_callback(knowledge.drop)
        await knowledge.schema(schema if schema is not None else knowledge_schema())
        await workflow.create()
        stack.push_async_callback(workflow.drop)
        await workflow.schema(workflow_schema())
        stack.push_async_callback(fga.delete_store)
        await fga.create_store("c1-m01-" + suffix)
        yield Session(knowledge, workflow, fga)
