"""Show authorized document reconstructions for the scoped-document fixture."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.load_fixture import Loader, api_client  # noqa: E402

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures/scoped-document/fixture.json"


async def demonstrate() -> dict[str, Any]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    document_id = fixture["document_id"]
    document_path = "/v1/documents/" + quote(document_id, safe="")

    async with api_client() as client:
        loader = await Loader.connect(client)
        result: dict[str, Any] = {"document_id": document_id, "readers": {}}
        for username in ("alice", "carol"):
            headers = {"Authorization": "Bearer " + await loader.user_token(username)}
            reconstruction = await client.get(document_path, headers=headers)
            if reconstruction.status_code != 200:
                raise RuntimeError(
                    f"Document reconstruction failed for {username} ({reconstruction.status_code})"
                )
            value = reconstruction.json()
            if not isinstance(value, dict) or not isinstance(value.get("parts"), list):
                raise RuntimeError(f"Document reconstruction for {username} was malformed")
            parts = value["parts"]
            if any(
                not isinstance(part, dict)
                or not isinstance(part.get("part_id"), str)
                or not isinstance(part.get("text"), str)
                for part in parts
            ):
                raise RuntimeError(f"Document parts for {username} were malformed")

            rendered = await client.get(
                document_path + "/render",
                params={"format": "markdown"},
                headers=headers,
            )
            if rendered.status_code != 200:
                raise RuntimeError(
                    f"Markdown rendering failed for {username} ({rendered.status_code})"
                )
            rendered_value = rendered.json()
            markdown = rendered_value.get("content") if isinstance(rendered_value, dict) else None
            if not isinstance(markdown, str):
                raise RuntimeError(f"Markdown rendering for {username} was malformed")

            result["readers"][username] = {
                "parts": [{"id": part["part_id"], "text": part["text"]} for part in parts],
                "markdown": markdown,
            }
        return result


def main() -> None:
    print(json.dumps(asyncio.run(demonstrate()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
