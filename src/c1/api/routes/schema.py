"""Installed profile definitions for form building (M12 D7a); no instance data."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from c1.api.deps import audit, get_principal, get_runtime
from c1.authorization.principal import Principal
from c1.changes.profiles import available_profile_names
from c1.model.profiles import PropertyDefinition
from c1.runtime import Runtime

router = APIRouter(prefix="/v1")


def _property(iri: str, definition: PropertyDefinition) -> dict[str, Any]:
    return {
        "iri": iri,
        "name": definition.name,
        "ranges": list(definition.ranges),
        "min_count": definition.min_count,
        "max_count": definition.max_count,
        "enum": list(definition.enum),
    }


@router.get("/schema", name="schema_read")
async def schema(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
    runtime: Annotated[Runtime, Depends(get_runtime)],
) -> dict[str, Any]:
    registry = runtime.registry
    profiles = []
    for name in sorted(registry.profiles):
        profile = registry.profiles[name]
        profiles.append(
            {
                "name": profile.name,
                "version": profile.version,
                "classes": [
                    {
                        "iri": iri,
                        "kind": definition.kind,
                        "properties": [
                            _property(prop, value)
                            for prop, value in sorted(definition.properties.items())
                        ],
                    }
                    for iri, definition in sorted(profile.classes.items())
                ],
            }
        )
    audit(request, principal, "schema_read")
    return {
        "instance": runtime.settings.instance_id,
        "profiles": profiles,
        "available_profiles": list(available_profile_names()),
    }
