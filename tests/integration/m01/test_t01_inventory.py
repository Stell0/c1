"""M01-T01: verify actual pinned artifacts and local license evidence."""

from __future__ import annotations

import json
import re

from probes.config import ROOT
from scripts.inventory import EVIDENCE, MANIFEST, build_inventory, write_inventory


def test_t01_inventory() -> None:
    inventory = build_inventory()  # Inspects real local images; no mocked artifact data.
    write_inventory(inventory)
    manifest = json.loads(MANIFEST.read_text())
    assert set(inventory["images"]) == set(manifest)
    for name, item in inventory["images"].items():
        expected = manifest[name]
        assert item["index_digest"] == expected["digest"]
        assert item["platform_digest"] == expected["platform_digest"]
        assert item["config_digest"] == expected["config_digest"]
        assert item["platform"] == expected["platform"]
        assert item["license_sha256"] == expected["license_sha256"]
        assert (ROOT / item["license_artifact"]).is_file()
        assert item["embedded_license_paths_checked"] == expected["embedded_license_paths"]
        assert item["embedded_notice_paths_checked"] == expected["embedded_notice_paths"]
        if item["embedded_licenses"]:
            assert item["license_sha256"] in item["embedded_licenses"].values()

    assert inventory["python"]["packages"]
    assert all(package["license_files"] for package in inventory["python"]["packages"])
    assert (EVIDENCE / "inventory.json").is_file()
    assert (EVIDENCE / "inventory.md").is_file()

    compose = (ROOT / "deployment/compose.yaml").read_text()
    configuration = compose + (ROOT / "deployment/.env.example").read_text()
    references = re.findall(r"^\s*image:\s*(\S+)", compose, flags=re.MULTILINE)
    assert references
    assert set(references) == {item["reference"] for item in inventory["images"].values()}
    forbidden = (
        "vector",
        "insecure_user_header",
        "enterprise",
        "cloud",
        "openai",
        "anthropic",
        "cohere",
    )
    assert not any(term in configuration.lower() for term in forbidden)
