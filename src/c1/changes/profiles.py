"""Trusted bundled profile catalog for reviewed schema installation.

The caller selects an exact bundled alias, never a filesystem path. A manifest
may have a different profile name from its catalog alias.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

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


# Parsed trusted catalog files, keyed by the exact bytes they were parsed from
# (M09a D5). Registries returned from here are shared and must not be mutated;
# the installed schema is still read freshly by every caller that checks it.
_PARSED: dict[tuple[str, ...], tuple[ProfileRegistry, str]] = {}
_SELECTIONS: dict[tuple[str, ...], ProfileRegistry] = {}


def _files_digest(*directories: Path) -> str:
    digest = hashlib.sha256()
    for directory in directories:
        for name in ("profile.json", "context.jsonld", "shapes.ttl"):
            path = directory / name
            digest.update(str(path).encode() + b"\0")
            digest.update(path.read_bytes() if path.is_file() else b"<absent>")
            digest.update(b"\0")
    return digest.hexdigest()


def _core_directory() -> Path:
    return _catalog_root().parent / "core"


def _cached_candidate(alias: str) -> tuple[ProfileRegistry, str]:
    """Shared parsed candidate; callers inside this module only read it."""
    directory = _catalog_entries().get(alias)
    if directory is None:
        raise ValueError("profile is not in the trusted local catalog")
    key = (alias, _files_digest(_core_directory(), directory))
    cached = _PARSED.get(key)
    if cached is not None:
        return cached
    registry = ProfileRegistry()
    registry.load(directory)
    names = set(registry.profiles) - {"core"}
    if len(names) != 1:
        raise ValueError("bundled candidate must declare exactly one extension profile")
    result = (registry, names.pop())
    _PARSED[key] = result
    return result


def load_candidate(alias: str) -> tuple[ProfileRegistry, str]:
    """Load core and one trusted candidate; return its manifest profile name.

    Returns a private copy: callers may extend the registry they receive.
    """
    registry, name = _cached_candidate(alias)
    return copy.deepcopy(registry), name


def _selected_registry(directories: list[Path]) -> ProfileRegistry:
    """Core plus the selected catalog profiles, parsed once per exact file content."""
    key = (_files_digest(_core_directory(), *directories), *(str(d) for d in directories))
    cached = _SELECTIONS.get(key)
    if cached is not None:
        return cached
    registry = ProfileRegistry()
    for directory in directories:
        registry.load(directory)
    _SELECTIONS[key] = registry
    return registry


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
    core = _selected_registry([])
    await assert_installed_profiles(client, core)
    actual_schema = await client.schema_documents()
    core_schema = generated_core_schema(core)
    entries = _catalog_entries()
    grouped: dict[str, list[tuple[Path, ProfileRegistry]]] = {}
    for alias, directory in entries.items():
        candidate, name = _cached_candidate(alias)
        grouped.setdefault(name, []).append((directory, candidate))
    selected: list[Path] = []
    names = sorted(grouped)
    # M14a: read every catalog marker concurrently (bounded); same decisions.
    gate = asyncio.Semaphore(8)

    async def read_marker(name: str) -> dict[str, Any] | None:
        async with gate:
            return await client.get(_marker_id(grouped[name][0][1], client, name))

    markers = await asyncio.gather(*(read_marker(name) for name in names))
    for name, stored in zip(names, markers, strict=True):
        alternatives = grouped[name]
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
    registry = copy.deepcopy(_selected_registry(selected))
    expected = [*core_schema]
    for name in registry.profiles:
        if name != "core":
            expected.extend(generated_classes(registry, name))
    if len(actual_schema) != len(expected) or any(item not in actual_schema for item in expected):
        raise StorageError("C1-ST-006", "installed profile schema is partial or unknown")
    await assert_installed_profiles(client, registry)
    return registry
