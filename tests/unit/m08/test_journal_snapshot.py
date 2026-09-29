"""A journal listing is reused only at the identical backend data version."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from c1.authorization.journal import Journal, _document_id


class FakeStorage:
    def __init__(self) -> None:
        self.version = "branch:one"
        self.listings = 0
        self.documents: list[dict[str, Any]] = []

    def put(self, kind: str, key: str, payload: dict[str, Any]) -> None:
        self.documents.append(
            {
                "@type": "WorkflowEntry",
                "@id": _document_id(kind, key),
                "kind": kind,
                "key": key,
                "payload_json": json.dumps(payload, sort_keys=True, separators=(",", ":")),
            }
        )

    async def head(self) -> str:
        return self.version

    async def documents_at_version(self) -> tuple[str, list[dict[str, Any]]]:
        self.listings += 1
        return self.version, list(self.documents)


def _journal(storage: FakeStorage) -> Journal:
    journal = Journal.__new__(Journal)
    journal._storage = storage  # type: ignore[assignment]
    journal._snapshot = None
    return journal


def test_listing_reused_only_while_the_data_version_is_unchanged() -> None:
    storage = FakeStorage()
    storage.put("Operation", "one", {"state": "pending"})
    journal = _journal(storage)

    async def run() -> None:
        first = await journal.list("Operation")
        again = await journal.list("Operation")
        assert first == again == [{"state": "pending"}]
        assert storage.listings == 1
        # Returned payloads are copies; a caller cannot alter the snapshot.
        first[0]["state"] = "tampered"
        assert await journal.list("Operation") == [{"state": "pending"}]
        # Any write changes the data version, which forces a fresh listing.
        storage.put("Operation", "two", {"state": "applied"})
        storage.version = "branch:two"
        assert len(await journal.list("Operation")) == 2
        assert storage.listings == 2
        many = await journal.list_many({"Operation", "Binding"})
        assert len(many["Operation"]) == 2 and many["Binding"] == []
        assert storage.listings == 2

    asyncio.run(run())
