"""Round-trip the M02 fixture in a disposable database on the development stack."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from uuid import uuid4

from c1.interchange import export_jsonld, import_jsonld
from c1.model.profiles import ProfileRegistry
from c1.storage.terminus import StorageConfig, Terminus
from probes.config import Settings


async def demonstrate(fixture: Path, database: str) -> dict[str, object]:
    if not re.fullmatch(r"c1_m02_demo_[a-z0-9_]+", database):
        raise ValueError("Demo database must start with c1_m02_demo_ and use safe characters")
    path = fixture / "fixture.jsonld" if fixture.is_dir() else fixture
    registry = ProfileRegistry()
    batch = import_jsonld(json.loads(path.read_text(encoding="utf-8")), registry)
    settings = Settings.load()
    config = StorageConfig(
        url=settings.terminus_url,
        password=settings.terminus_password,
        organization="admin",
        database=database,
        instance_base="urn:c1:instance:dev:",
    )
    async with Terminus(config) as client:
        # Existing databases cause create() to fail; never drop a reused database.
        await client.create()
        try:
            await client.install_profile(registry)
            await client.write_records(batch, registry, expected_head=await client.head())
            return export_jsonld(await client.read_records(registry), registry)
        finally:
            await client.drop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path("fixtures/core-knowledge"))
    parser.add_argument("--database", default="c1_m02_demo_" + uuid4().hex)
    arguments = parser.parse_args()
    print(json.dumps(asyncio.run(demonstrate(arguments.fixture, arguments.database)), indent=2))


if __name__ == "__main__":
    main()
