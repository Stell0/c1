"""Stable diagnostics shared by model, interchange, and profile validation."""

from typing import Literal, NoReturn

from pydantic import BaseModel, ConfigDict


class Diagnostic(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    severity: Literal["error", "warning", "info"]
    path: str
    message: str


class ProfileError(ValueError):
    """A supported-profile rejection with stable, machine-readable reasons."""

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        super().__init__("; ".join(f"{item.code}: {item.message}" for item in diagnostics))


def fail(code: str, message: str, path: str = "") -> NoReturn:
    raise ProfileError([Diagnostic(code=code, severity="error", path=path, message=message)])
