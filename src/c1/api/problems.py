"""Small, content-free RFC 9457 Problem Details responses."""

from typing import Literal

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from c1.model.diagnostics import ProfileError

ProblemKind = Literal["authentication", "authorization", "validation", "not-found", "unavailable"]


class ProblemDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str
    title: str
    status: int
    detail: str


_PROBLEMS: dict[int, tuple[ProblemKind, str, str]] = {
    400: ("validation", "Bad Request", "Invalid request"),
    401: ("authentication", "Unauthorized", "Authentication required"),
    403: ("authorization", "Forbidden", "Operation not permitted"),
    404: ("not-found", "Not Found", "Resource not found"),
    409: ("validation", "Conflict", "Operation conflicts with current state"),
    413: ("validation", "Payload Too Large", "Request body is too large"),
    422: ("validation", "Unprocessable Content", "Invalid request"),
    503: ("unavailable", "Service Unavailable", "Service unavailable"),
}


def problem(status: int) -> JSONResponse:
    if status == 500:
        value = ProblemDetails(
            type="about:blank#unavailable",
            title="Internal Server Error",
            status=500,
            detail="Request could not be completed",
        )
    else:
        kind, title, detail = _PROBLEMS.get(status, _PROBLEMS[503])
        value = ProblemDetails(
            type=f"about:blank#{kind}", title=title, status=status, detail=detail
        )
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content=value.model_dump(),
    )


async def validation_problem(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return problem(400)


async def profile_problem(_request: Request, _exc: ProfileError) -> JSONResponse:
    return problem(400)


async def http_problem(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return problem(exc.status_code if exc.status_code in _PROBLEMS else 500)
