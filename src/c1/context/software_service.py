"""Test-development context requests over the software profile (M09 D1, D8).

One authorized selection feeds anchor and target resolution, the selection
stage, and both renderings. Continuations reuse the M07 revision-bound signed
cursor; the resolved target is part of the checkpoint, so a changed or
unreadable member forces a restart instead of a substitution.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

from c1.context.budget import build_page, prepare_units
from c1.context.errors import ContextError
from c1.context.profiles import SoftwareContextProfile
from c1.context.request import ContextRequest, request_digest
from c1.context.software import (
    SoftwareSelection,
    coverage_summary,
    resolve_software_anchor,
)
from c1.context.software_render import render_software_markdown, render_software_structured
from c1.query.cursor import CursorError
from c1.query.plan import QueryPlanError
from c1.storage.schema import profile_digest

if TYPE_CHECKING:
    from c1.authorization.principal import Principal
    from c1.context.service import ContextService

ORDER = "context-software-units-v1"


async def build_software_context(
    service: ContextService,
    principal: Principal,
    request: ContextRequest,
    profile: SoftwareContextProfile,
    *,
    deadline: float,
) -> dict[str, Any]:
    from c1.context.service import _checkpoint, _digest

    runtime = service.runtime
    catalog = runtime.context_catalog()
    if "software" not in runtime.registry.profiles:
        raise ContextError(400, "C1-CX-002", "unknown_context_profile")
    if (
        request.topics
        or request.keywords_all
        or request.keywords_any
        or request.fields
        or request.project_ref is not None
    ):
        raise ContextError(400, "C1-CX-001", "unsupported_selector")
    if request.target is None:
        raise ContextError(400, "C1-CX-001", "target_required")
    if request.goal is None:
        raise ContextError(400, "C1-CX-001", "goal_required")
    digest = _digest(
        {
            "request": request_digest(request),
            "context_profile": catalog.digest(request.profile, request.profile_version),
            "schemas": {
                name: profile_digest(value)
                for name, value in sorted(runtime.registry.profiles.items())
            },
        }
    )
    position = None
    if request.cursor:
        try:
            position = runtime.query.codec.decode(
                request.cursor,
                principal=principal.id,
                filter_digest=digest,
                order=ORDER,
                revision=request.revision,
            )
            if not re.fullmatch(r"0|[1-9][0-9]{0,2}", position.last_key[0]):
                raise CursorError("invalid context position")
            if not re.fullmatch(r"[0-9a-f]{64}", position.last_key[1]):
                raise CursorError("invalid context prefix")
        except CursorError as exc:
            raise ContextError(409, "C1-CX-011", "restart_required") from exc
    revision = position.revision if position else request.revision
    if revision is None:
        head, (plan, _) = await asyncio.gather(
            runtime.knowledge.head(), runtime.query.selection(principal, deadline=deadline)
        )
        revision = head
    else:
        plan, _ = await runtime.query.selection(principal, deadline=deadline)
    records = dict((await runtime.query.records(plan, revision, deadline=deadline)).items())
    try:
        target = runtime.software.resolve_target(records, request.target.spec())
        anchor = resolve_software_anchor(records, request.anchor, profile)
    except QueryPlanError as exc:
        if position is not None:
            raise ContextError(409, "C1-CX-011", "restart_required") from exc
        raise ContextError(exc.status, exc.code, exc.reason) from exc
    if anchor["outcome"] != "resolved":
        if position is not None:
            raise ContextError(409, "C1-CX-011", "restart_required")
        await runtime.query.planner.finalize(principal, plan, deadline=deadline)
        return {"outcome": anchor["outcome"], "revision": revision, "anchor_resolution": anchor}
    anchor_node = records[anchor["anchor"]["id"]]
    selection = SoftwareSelection(records, target, anchor_node, profile, deadline=deadline)
    built = selection.build()
    if built["outcome"] != "resolved":
        if position is not None:
            raise ContextError(409, "C1-CX-011", "restart_required")
        await runtime.query.planner.finalize(principal, plan, deadline=deadline)
        return {
            "outcome": built["outcome"],
            "revision": revision,
            "anchor_resolution": anchor,
            "reason": built["reason"],
            "target": target.describe(),
        }
    units = selection.units
    public_units = prepare_units(units)
    described = target.describe()
    coverage = coverage_summary(records, target)
    interpretation = {
        "profile": profile.name,
        "profile_version": profile.version,
        "profile_digest": catalog.digest(profile.name, profile.version),
        "revision": revision,
        "anchor": anchor["anchor"],
        "goal": request.goal,
        "target_symbols": [
            {"id": node.id, "label": unit_label}
            for node in built["symbols"]
            for unit_label in [_label(node)]
        ],
        "coverage": coverage,
    }
    common = frozenset(
        {
            anchor_node.id,
            *target.snapshots,
            *target.contracts,
            *target.configurations,
            *(item["id"] for item in coverage),
            *(gap["record_id"] for gap in selection.gaps if "record_id" in gap),
        }
    )
    # The target and gaps are part of every page, so the checkpoint covers them.
    checkpoint_interpretation = {**interpretation, "target": described, "gaps": selection.gaps}
    offset = int(position.last_key[0]) if position else 0
    if offset > len(units) or (
        position
        and position.last_key[1]
        != _checkpoint(
            units, public_units, offset, checkpoint_interpretation, records, plan, common
        )
    ):
        raise ContextError(409, "C1-CX-011", "restart_required")

    def cursor_for_offset(end: int) -> str | None:
        if end >= len(units):
            return None
        return runtime.query.codec.encode(
            principal=principal.id,
            revision=revision,
            filter_digest=digest,
            order=ORDER,
            last_key=(
                str(end),
                _checkpoint(
                    units, public_units, end, checkpoint_interpretation, records, plan, common
                ),
            ),
        )

    base = {
        "interpretation": interpretation,
        "target": described,
        "gaps": selection.gaps,
        "anchor_label": anchor["anchor"]["label"],
    }
    page = build_page(
        base,
        public_units,
        offset=offset,
        maximum=request.budget.maximum,
        cursor_for_offset=cursor_for_offset,
        deadline=deadline,
        render_structured=render_software_structured,
        render_markdown=render_software_markdown,
    )
    await runtime.query.planner.finalize(principal, plan, deadline=deadline)
    response: dict[str, Any] = {
        "outcome": "resolved",
        "revision": revision,
        "bounds": page["bounds"],
    }
    for format in request.formats:
        response[format] = page[format]
    return response


def _label(node: Any) -> str | None:
    from c1.context.software import _label as label

    return label(node)
