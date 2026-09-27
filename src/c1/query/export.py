"""JSON-LD export boundary for an already authorized query selection."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from c1.interchange.export import export_jsonld
from c1.model.nodes import NodeRecord
from c1.model.profiles import ProfileRegistry


def export_authorized(
    records: Iterable[NodeRecord],
    registry: ProfileRegistry | None = None,
    *,
    authorized_ids: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Export a selected page; the caller owns current authorization and paging.

    ``authorized_ids`` is an optional guard against accidentally passing a
    broader fetched batch than the authorization plan selected. It does not
    replace the plan's live authorization and release checks.
    """
    selected = list(records)
    if authorized_ids is not None and any(record.id not in authorized_ids for record in selected):
        raise ValueError("export contains a record outside the authorized selection")
    return export_jsonld(selected, registry)
