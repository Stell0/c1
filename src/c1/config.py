"""Trusted deployment configuration for the single C1 application process."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from c1.model.ids import validate_iri

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_ALIAS = re.compile(r"^[a-z][a-z0-9_-]*$")
_CRASH_POINTS = frozenset({"journal", "commit", "tuple", "confirm"})


def _url(value: str, name: str, *, allow_path: bool = False) -> None:
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and (allow_path or parsed.path in {"", "/"})
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be a trusted HTTP(S) URL without credentials or query")


def _boolean(value: str, name: str) -> bool:
    match value.lower():
        case "true" | "1":
            return True
        case "false" | "0":
            return False
        case _:
            raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    """Configuration chosen at startup, never from a request or stored record."""

    instance_id: str
    instance_base: str
    issuer: str
    issuer_alias: str
    audience: str
    fga_url: str
    fga_token: str = field(repr=False)
    fga_store: str
    fga_model: str
    terminus_url: str
    terminus_password: str = field(repr=False)
    organization: str
    knowledge_database: str
    workflow_database: str
    lock_path: Path
    independent_review: bool = True
    enable_probe_routes: bool = False
    crash_after: str | None = None

    def __post_init__(self) -> None:
        if not _NAME.fullmatch(self.instance_id):
            raise ValueError("C1_INSTANCE_ID is invalid")
        validate_iri(self.instance_base)
        if not self.instance_base.endswith((":", "/", "#")):
            raise ValueError("C1_INSTANCE_IRI_BASE needs a namespace delimiter")
        if not _ALIAS.fullmatch(self.issuer_alias):
            raise ValueError("C1_ISSUER_ALIAS is invalid")
        _url(self.issuer, "C1_ISSUER", allow_path=True)
        _url(self.fga_url, "C1_FGA_URL")
        _url(self.terminus_url, "C1_TERMINUS_URL")
        if not self.audience or any(char.isspace() for char in self.audience):
            raise ValueError("C1_AUDIENCE is invalid")
        if not self.fga_token or not self.terminus_password:
            raise ValueError("Backend credentials are required")
        if not self.fga_store or not self.fga_model:
            raise ValueError("Configured OpenFGA store and model IDs are required")
        for name, value in (
            ("C1_ORGANIZATION", self.organization),
            ("C1_KNOWLEDGE_DATABASE", self.knowledge_database),
            ("C1_WORKFLOW_DATABASE", self.workflow_database),
        ):
            if not _NAME.fullmatch(value):
                raise ValueError(f"{name} is invalid")
        if self.knowledge_database == self.workflow_database:
            raise ValueError("Knowledge and workflow databases must be distinct")
        if not self.lock_path.is_absolute():
            raise ValueError("C1_LOCK_PATH must be absolute")
        if self.crash_after is not None and (
            not self.enable_probe_routes or self.crash_after not in _CRASH_POINTS
        ):
            raise ValueError("Crash points require the enabled probe routes")

    @classmethod
    def from_env(cls) -> Settings:
        """Read only startup-owned C1_* process environment variables."""
        required = (
            "C1_ISSUER",
            "C1_FGA_TOKEN",
            "C1_FGA_STORE",
            "C1_FGA_MODEL",
            "C1_TERMINUS_PASSWORD",
            "C1_KNOWLEDGE_DATABASE",
            "C1_WORKFLOW_DATABASE",
        )
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise ValueError("Missing deployment configuration: " + ", ".join(missing))
        get = os.environ.get
        return cls(
            instance_id=get("C1_INSTANCE_ID", "c1-dev"),
            instance_base=get("C1_INSTANCE_IRI_BASE", "urn:c1:instance:dev:"),
            issuer=os.environ["C1_ISSUER"],
            issuer_alias=get("C1_ISSUER_ALIAS", "c1-dev"),
            audience=get("C1_AUDIENCE", "c1-api"),
            fga_url=get("C1_FGA_URL", "http://127.0.0.1:18080"),
            fga_token=os.environ["C1_FGA_TOKEN"],
            fga_store=os.environ["C1_FGA_STORE"],
            fga_model=os.environ["C1_FGA_MODEL"],
            terminus_url=get("C1_TERMINUS_URL", "http://127.0.0.1:16363"),
            terminus_password=os.environ["C1_TERMINUS_PASSWORD"],
            organization=get("C1_ORGANIZATION", "admin"),
            knowledge_database=os.environ["C1_KNOWLEDGE_DATABASE"],
            workflow_database=os.environ["C1_WORKFLOW_DATABASE"],
            lock_path=Path(get("C1_LOCK_PATH", "/tmp/c1-security.lock")),
            independent_review=_boolean(
                get("C1_INDEPENDENT_REVIEW", "true"), "C1_INDEPENDENT_REVIEW"
            ),
            enable_probe_routes=_boolean(
                get("C1_ENABLE_PROBE_ROUTES", "false"), "C1_ENABLE_PROBE_ROUTES"
            ),
            crash_after=get("C1_CRASH_AFTER"),
        )
