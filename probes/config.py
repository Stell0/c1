"""Private loopback-only configuration for the disposable M01 stack."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "deployment/.env"


def environment() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line and not line.startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value
    return values


@dataclass(frozen=True, repr=False)
class Settings:
    terminus_url: str = "http://127.0.0.1:16363"
    fga_url: str = "http://127.0.0.1:18080"
    keycloak_url: str = "http://127.0.0.1:18090"
    terminus_password: str = ""
    fga_token: str = ""

    @classmethod
    def load(cls) -> Settings:
        values = environment()
        if not values.get("C1_TERMINUS_PASSWORD") or not values.get("C1_FGA_TOKEN"):
            raise RuntimeError("M01 credentials missing; run make stack-up")
        return cls(
            terminus_password=values["C1_TERMINUS_PASSWORD"],
            fga_token=values["C1_FGA_TOKEN"],
        )


def runtime() -> str:
    backend = os.environ.get("C1_CONTAINER_RUNTIME", "podman")
    if backend not in {"podman", "docker"}:
        raise ValueError("M01 supports only podman or docker")
    return backend
