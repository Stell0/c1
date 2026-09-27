"""Request-scoped trusted objects populated by the application boundary."""

from typing import cast

from fastapi import Request

from c1.authorization.principal import Principal
from c1.runtime import Runtime


async def get_runtime(request: Request) -> Runtime:
    return cast(Runtime, request.app.state.runtime)


async def get_principal(request: Request) -> Principal:
    return cast(Principal, request.state.principal)


def audit(
    request: Request,
    principal: Principal,
    operation: str,
    *,
    target: str = "",
    outcome: str = "allowed",
    reason: str = "",
) -> None:
    runtime = cast(Runtime, request.app.state.runtime)
    runtime.audit.emit(
        principal=principal.id,
        operation=operation,
        target=target,
        outcome=outcome,
        reason=reason,
        correlation_id=request.state.correlation_id,
    )
