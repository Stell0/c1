"""Trusted bundled profile catalog for reviewed schema installation.

The caller selects an exact bundled alias, never a filesystem path. A manifest
may have a different profile name from its catalog alias.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from c1.model.diagnostics import Diagnostic
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry, compare_profiles
from c1.storage.mapping import document_to_record, installed_profile_iri, record_to_document
from c1.storage.schema import (
    _profile_marker,
    assert_installed_profiles,
    generated_classes,
    generated_core_schema,
)
from c1.storage.terminus import StorageError

if TYPE_CHECKING:
    from c1.storage.terminus import Terminus

_CORE = "urn:c1:ns:core#"


def _catalog_root() -> Path:
    package = Path(__file__).resolve().parents[1] / "profiles" / "available"
    repository = Path(__file__).resolve().parents[3] / "profiles" / "available"
    root = package if package.is_dir() else repository
    if root.is_symlink() or not root.is_dir():
        raise ValueError("trusted local profile catalog is unavailable")
    return root


def _catalog_entries() -> dict[str, Path]:
    root = _catalog_root()
    result: dict[str, Path] = {}
    for item in sorted(root.iterdir()):
        if item.is_symlink():
            raise ValueError("catalog symlink is unsupported")
        if item.is_dir() and (item / "profile.json").is_file():
            result[item.name] = item
    return result


def available_profile_names() -> tuple[str, ...]:
    """Return aliases found under the fixed, bundled catalog root."""
    return tuple(_catalog_entries())


def load_candidate(alias: str) -> tuple[ProfileRegistry, str]:
    """Load core and one trusted candidate; return its manifest profile name."""
    directory = _catalog_entries().get(alias)
    if directory is None:
        raise ValueError("profile is not in the trusted local catalog")
    registry = ProfileRegistry()
    registry.load(directory)
    names = set(registry.profiles) - {"core"}
    if len(names) != 1:
        raise ValueError("bundled candidate must declare exactly one extension profile")
    return registry, names.pop()


def compare_candidate(installed: ProfileRegistry, alias: str) -> list[Diagnostic]:
    """Compare a candidate to the installed profile; migration remains refused."""
    candidate, name = load_candidate(alias)
    previous = installed.profiles.get(name)
    if previous is None:
        # Check collisions with every already installed extension, not only core.
        combined = ProfileRegistry()
        entries = _catalog_entries()
        for installed_name in sorted(set(installed.profiles) - {"core"}):
            matches = [
                path
                for path in entries.values()
                if load_candidate(path.name)[0].profiles.get(installed_name)
                == installed.profiles[installed_name]
            ]
            if len(matches) != 1:
                raise ValueError("installed profile is not in the trusted catalog")
            combined.load(matches[0])
        combined.load(entries[alias])
        return []
    return compare_profiles(previous, candidate.profiles[name])


def _marker_id(registry: ProfileRegistry, client: Terminus, name: str) -> str:
    marker = NodeRecord(
        id=installed_profile_iri(name),
        types=[_CORE + "SchemaProfile"],
        properties={},
    )
    return str(record_to_document(marker, registry, client.config.instance_base)["@id"])


async def detect_installed_registry(client: Terminus) -> ProfileRegistry:
    """Return installed registry only when both schema and marker agree.

    A schema commit without its marker, an orphan marker, or an unknown class
    is not accepted as an installed profile at startup.
    """
    core = ProfileRegistry()
    await assert_installed_profiles(client, core)
    actual_schema = await client.schema_documents()
    core_schema = generated_core_schema(core)
    entries = _catalog_entries()
    grouped: dict[str, list[tuple[Path, ProfileRegistry]]] = {}
    for alias, directory in entries.items():
        candidate, name = load_candidate(alias)
        grouped.setdefault(name, []).append((directory, candidate))
    selected: list[Path] = []
    for name, alternatives in sorted(grouped.items()):
        marker_id = _marker_id(alternatives[0][1], client, name)
        stored = await client.get(marker_id)
        if stored is None:
            continue
        matches = [
            directory
            for directory, candidate in alternatives
            if document_to_record(stored, candidate) == _profile_marker(candidate, name)
        ]
        if len(matches) != 1:
            raise StorageError("C1-ST-006", "extension marker is unknown or ambiguous")
        selected.extend(matches)
    registry = ProfileRegistry()
    for directory in selected:
        registry.load(directory)
    expected = [*core_schema]
    for name in registry.profiles:
        if name != "core":
            expected.extend(generated_classes(registry, name))
    if len(actual_schema) != len(expected) or any(item not in actual_schema for item in expected):
        raise StorageError("C1-ST-006", "installed profile schema is partial or unknown")
    await assert_installed_profiles(client, registry)
    return registry
