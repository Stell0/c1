"""M01 single-writer experiment with a commit-metadata receipt and projection."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from probes.terminus import Terminus

_LOCKS: dict[str, asyncio.Lock] = {}


def digest(documents: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(documents, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ProbeWriter:
    def __init__(self, knowledge: Terminus, workflow: Terminus) -> None:
        self.knowledge = knowledge
        self.workflow = workflow
        self.lock = _LOCKS.setdefault(knowledge.database, asyncio.Lock())

    async def find(self, changeset: str, principal: str, payload_digest: str) -> str | None:
        matches = []
        for commit in await self.knowledge.log():
            try:
                receipt = json.loads(commit.get("message", ""))
            except (ValueError, TypeError):
                continue
            if not isinstance(receipt, dict) or receipt.get("m01") != 1:
                continue
            if (receipt.get("changeset"), receipt.get("principal"), receipt.get("repository")) != (
                changeset,
                principal,
                self.knowledge.database,
            ):
                continue
            if receipt.get("digest") != payload_digest:
                raise ValueError("Idempotency key reused with different payload")
            matches.append("branch:" + commit["identifier"])
        if len(matches) > 1:
            raise RuntimeError("Multiple durable receipts for the same request")
        return matches[0] if matches else None

    async def apply(
        self,
        changeset: str,
        documents: list[dict[str, Any]],
        base: str,
        principal: str = "user:u",
        discard_response: bool = False,
    ) -> str:
        async with self.lock:
            payload_digest = digest(documents)
            commit = await self.find(changeset, principal, payload_digest)
            if commit is None:
                message = json.dumps(
                    {
                        "m01": 1,
                        "changeset": changeset,
                        "principal": principal,
                        "repository": self.knowledge.database,
                        "digest": payload_digest,
                    },
                    sort_keys=True,
                )
                commit = await self.knowledge.insert(documents, message, base)
                if discard_response:
                    # Real backend commit occurred. Simulate losing its acknowledgement
                    # before saving the workflow projection, then reconcile from log.
                    raise ConnectionError("Injected lost commit acknowledgement")
            receipt_id = (
                "Receipt/" + hashlib.sha256((principal + "\0" + changeset).encode()).hexdigest()
            )
            receipt = {
                "@type": "Receipt",
                "@id": receipt_id,
                "changeset": changeset,
                "principal": principal,
                "digest": payload_digest,
                "knowledge_commit": commit,
            }
            current = await self.workflow.get(receipt_id)
            if current is None:
                await self.workflow.insert(
                    [receipt], "M01 receipt projection", await self.workflow.head()
                )
            elif any(current.get(key) != value for key, value in receipt.items() if key != "@id"):
                raise RuntimeError("Receipt projection conflicts with durable knowledge receipt")
            return commit
