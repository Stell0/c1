"""Show graph context beside exact keywords for the synthetic batteries fixture."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from c1.context.resolve import candidate  # noqa: E402
from c1.documents.render import escape_markdown_text  # noqa: E402
from c1.model.nodes import NodeRecord  # noqa: E402
from probes.config import ROOT  # noqa: E402
from scripts.load_fixture import Loader, api_client  # noqa: E402

EXPECTED = ROOT / "fixtures/cross-project-batteries/expected"


def expected_actors(
    value: Any, principals: dict[str, str], *, encode: bool, markdown: bool = False
) -> Any:
    """Resolve expected-template actors; actual response attribution stays intact."""
    if isinstance(value, dict):
        return {
            key: expected_actors(item, principals, encode=encode, markdown=markdown)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            expected_actors(item, principals, encode=encode, markdown=markdown) for item in value
        ]
    if isinstance(value, str):
        for producer, actual in principals.items():
            placeholder = "urn:c1:fixture:producer:" + producer
            if markdown:
                actual = escape_markdown_text(actual)
            original, replacement = (actual, placeholder) if encode else (placeholder, actual)
            value = value.replace(original, replacement)
    return value


def canonical(value: Any, revision: str) -> Any:
    """Keep meaningful IDs and source revisions; remove only declared volatility."""
    if isinstance(value, dict):
        return {
            key: canonical(item, revision)
            for key, item in value.items()
            if key not in {"generated_at", "request_id", "revision"}
        }
    if isinstance(value, list):
        return [canonical(item, revision) for item in value]
    if isinstance(value, str):
        return value.replace(revision, "<revision>")
    return value


async def demonstrate(*, write_goldens: bool = False) -> dict[str, Any]:
    fixture = json.loads((ROOT / "fixtures/cross-project-batteries/fixture.json").read_text())
    async with api_client() as client:
        loader = await Loader.connect(client)
        dave = await loader.request(
            "POST",
            "/v1/context",
            actor="dave",
            json_body={
                "profile": "graph-context",
                "profile_version": "1",
                "anchor": {"label": "Tesla"},
                "topics": ["batteries"],
            },
        )
        if dave.get("outcome") != "resolved":
            raise RuntimeError("Load the cross-project-batteries fixture before demonstrating it")
        keywords = await loader.request(
            "GET", "/v1/entities?keywords_all=batteries,tesla", actor="dave"
        )
        result = {
            "markdown": dave["markdown"],
            "exact_keywords_all": [item["id"] for item in keywords["items"]],
        }
        if write_goldens:
            principals = {
                "papertrader": await loader.whoami("service"),
                "robotelier": await loader.whoami("robotelier"),
            }
            carol = await loader.request(
                "POST",
                "/v1/context",
                actor="reviewer",
                json_body={
                    "profile": "graph-context",
                    "profile_version": "1",
                    "anchor": {"label": "Tesla"},
                    "topics": ["batteries"],
                    "revision": dave["revision"],
                },
            )
            tesla = next(
                item
                for item in fixture["producers"]["papertrader"]
                if item["id"] == fixture["ids"]["tesla"]
            )
            candidates = sorted(
                [
                    candidate(
                        NodeRecord.model_validate(
                            {key: item[key] for key in ("id", "types", "properties")}
                        )
                    )
                    for item in (tesla, fixture["ambiguity"][0])
                ],
                key=lambda item: item["id"],
            )
            values = {
                "context-dave.md": dave["markdown"],
                "context-dave.json": dave["structured"],
                "context-carol.md": carol["markdown"],
                "keywords-all.json": result["exact_keywords_all"],
                "ambiguity.json": candidates,
            }
            for name, value in values.items():
                normalized = canonical(value, dave["revision"])
                normalized = expected_actors(
                    normalized, principals, encode=True, markdown=name.endswith(".md")
                )
                content = (
                    normalized
                    if isinstance(normalized, str)
                    else json.dumps(normalized, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
                )
                (EXPECTED / name).write_text(content, encoding="utf-8")
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-goldens",
        action="store_true",
        help="explicitly regenerate packages for review; never run implicitly",
    )
    args = parser.parse_args()
    value = asyncio.run(demonstrate(write_goldens=args.write_goldens))
    print(value["markdown"])
    print("Exact keywords ALL [batteries, tesla]: " + json.dumps(value["exact_keywords_all"]))


if __name__ == "__main__":
    main()
