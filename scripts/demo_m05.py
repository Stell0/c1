"""Show the directory query results visible to each local demo principal."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.load_fixture import Loader, api_client  # noqa: E402


async def demonstrate() -> dict[str, object]:
    async with api_client() as client:
        loader = await Loader.connect(client)
        results: dict[str, object] = {}
        for username in ("alice", "bob", "carol", "dave"):
            headers = {"Authorization": "Bearer " + await loader.user_token(username)}
            response = await client.get(
                "/v1/entities",
                params={"label": "Ada Example", "label_mode": "exact", "limit": 10},
                headers=headers,
            )
            if response.status_code != 200:
                raise RuntimeError(f"Entity query failed for {username} ({response.status_code})")
            people = response.json().get("items", [])
            if len(people) != 1:
                raise RuntimeError(f"Expected one readable Ada Example entity for {username}")
            person_id = people[0].get("id")
            assertions = await client.get(
                "/v1/assertions",
                params={"subject": person_id, "limit": 10},
                headers=headers,
            )
            if assertions.status_code != 200:
                raise RuntimeError(
                    f"Assertion query failed for {username} ({assertions.status_code})"
                )
            payload = assertions.json()
            results[username] = {
                "person_id": person_id,
                "assertion_ids": [item["id"] for item in payload.get("items", [])],
                "count": payload.get("count"),
            }
        return results


def main() -> None:
    print(json.dumps(asyncio.run(demonstrate()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
