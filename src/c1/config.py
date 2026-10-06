"""Trusted deployment configuration for the single C1 application process."""

from __future__ import annotations

import os
import re
import ssl
import stat
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


SECRET_NAMES = frozenset(
    {"C1_TERMINUS_PASSWORD", "C1_FGA_TOKEN", "C1_CURSOR_SECRET", "C1_EXPLORER_CLIENT_SECRET"}
)


def secret_value(name: str) -> str | None:
    """A secret from ``NAME`` or from the file named by ``NAME_FILE`` (M13 D4).

    Exactly one form may be set. The file must be an absolute, regular,
    non-symlink file readable only by its owner or group (mode 0400 or 0440).
    Values are never included in error messages.
    """
    direct = os.environ.get(name)
    path_text = os.environ.get(name + "_FILE")
    if direct and path_text:
        raise ValueError(f"Set {name} or {name}_FILE, not both")
    if not path_text:
        return direct or None
    path = Path(path_text)
    if not path.is_absolute():
        raise ValueError(f"{name}_FILE must be an absolute path")
    try:
        info = path.lstat()
    except OSError:
        raise ValueError(f"{name}_FILE is not readable") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{name}_FILE must be a regular file, not a symlink")
    if info.st_mode & 0o337:
        raise ValueError(f"{name}_FILE must have mode 0400 or 0440")
    try:
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError):
        raise ValueError(f"{name}_FILE is not readable") from None
    if not value or "\n" in value:
        raise ValueError(f"{name}_FILE must contain one non-empty line")
    return value


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
    cursor_secret: str = field(default="", repr=False)
    query_candidate_limit: int = 5000
    max_readable_scopes: int = 500
    # M09 D12 (owner-approved 2026-09-30): 5,000 -> 10,000 ms default; cap unchanged.
    query_time_budget_ms: int = 10000
    # M09 D13: OpenFGA and OIDC client timeouts; default unchanged (M07 D22).
    backend_timeout_s: float = 5.0
    # M14b D2: concurrent per-object OpenFGA reads when not scanning.
    fga_read_concurrency: int = 16
    # M13: a private CA bundle that identity (issuer, JWKS) requests trust.
    issuer_ca_file: Path | None = None

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
        for setting_name, setting_value, maximum in (
            ("C1_QUERY_CANDIDATE_LIMIT", self.query_candidate_limit, 5000),
            ("C1_MAX_READABLE_SCOPES", self.max_readable_scopes, 500),
            ("C1_QUERY_TIME_BUDGET_MS", self.query_time_budget_ms, 30000),
            ("C1_FGA_READ_CONCURRENCY", self.fga_read_concurrency, 64),
        ):
            if setting_value < 1 or setting_value > maximum:
                raise ValueError(f"{setting_name} must be between 1 and {maximum}")
        if not 1 <= self.backend_timeout_s <= 30:
            raise ValueError("C1_BACKEND_TIMEOUT_S must be between 1 and 30")
        if self.issuer_ca_file is not None and not self.issuer_ca_file.is_absolute():
            raise ValueError("C1_ISSUER_CA_FILE must be absolute")
        if self.cursor_secret and len(self.cursor_secret) < 32:
            raise ValueError("C1_CURSOR_SECRET must contain at least 32 characters")

    @classmethod
    def from_env(cls) -> Settings:
        """Read only startup-owned C1_* process environment variables."""
        required = (
            "C1_ISSUER",
            "C1_FGA_TOKEN",
            "C1_CURSOR_SECRET",
            "C1_FGA_STORE",
            "C1_FGA_MODEL",
            "C1_TERMINUS_PASSWORD",
            "C1_KNOWLEDGE_DATABASE",
            "C1_WORKFLOW_DATABASE",
        )
        missing = [
            name
            for name in required
            if not (secret_value(name) if name in SECRET_NAMES else os.environ.get(name))
        ]
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
            fga_token=secret_value("C1_FGA_TOKEN") or "",
            fga_store=os.environ["C1_FGA_STORE"],
            fga_model=os.environ["C1_FGA_MODEL"],
            terminus_url=get("C1_TERMINUS_URL", "http://127.0.0.1:16363"),
            terminus_password=secret_value("C1_TERMINUS_PASSWORD") or "",
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
            cursor_secret=secret_value("C1_CURSOR_SECRET") or "",
            query_candidate_limit=int(get("C1_QUERY_CANDIDATE_LIMIT", "5000")),
            max_readable_scopes=int(get("C1_MAX_READABLE_SCOPES", "500")),
            query_time_budget_ms=int(get("C1_QUERY_TIME_BUDGET_MS", "10000")),
            backend_timeout_s=float(get("C1_BACKEND_TIMEOUT_S", "5")),
            fga_read_concurrency=int(get("C1_FGA_READ_CONCURRENCY", "16")),
            issuer_ca_file=Path(get("C1_ISSUER_CA_FILE", "")) if get("C1_ISSUER_CA_FILE") else None,
        )

    def issuer_verify(self) -> ssl.SSLContext | bool:
        """TLS verification for identity requests: the private CA when configured."""
        if self.issuer_ca_file is None:
            return True
        return ssl.create_default_context(cafile=str(self.issuer_ca_file))


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


@dataclass(frozen=True)
class ExplorerSettings:
    """Browser Explorer startup configuration (M12 D12); never from a request."""

    origin: str
    client_id: str
    client_secret: str = field(repr=False)
    session_idle_s: int = 1800
    session_max_s: int = 28800

    def __post_init__(self) -> None:
        _url(self.origin, "C1_EXPLORER_ORIGIN")
        parsed = urlsplit(self.origin)
        if parsed.path not in {""} or self.origin.endswith("/"):
            raise ValueError("C1_EXPLORER_ORIGIN must be an origin without a path")
        if parsed.scheme != "https" and parsed.hostname not in _LOOPBACK_HOSTS:
            raise ValueError("C1_EXPLORER_ORIGIN must use HTTPS unless it is a loopback host")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", self.client_id):
            raise ValueError("C1_EXPLORER_CLIENT_ID is invalid")
        if len(self.client_secret) < 16:
            raise ValueError("C1_EXPLORER_CLIENT_SECRET is required")
        if not 60 <= self.session_idle_s <= 86400:
            raise ValueError("C1_EXPLORER_SESSION_IDLE_S must be between 60 and 86400")
        if not self.session_idle_s <= self.session_max_s <= 7 * 86400:
            raise ValueError("C1_EXPLORER_SESSION_MAX_S must be at least the idle timeout")

    @property
    def secure_transport(self) -> bool:
        return urlsplit(self.origin).scheme == "https"

    @property
    def redirect_uri(self) -> str:
        return self.origin + "/explorer/callback"

    @classmethod
    def from_env(cls) -> ExplorerSettings | None:
        """``None`` unless ``C1_EXPLORER_ENABLED`` is true; then all values are required."""
        get = os.environ.get
        if not _boolean(get("C1_EXPLORER_ENABLED", "false"), "C1_EXPLORER_ENABLED"):
            return None
        missing = [
            name
            for name in ("C1_EXPLORER_ORIGIN", "C1_EXPLORER_CLIENT_SECRET")
            if not (secret_value(name) if name in SECRET_NAMES else get(name))
        ]
        if missing:
            raise ValueError("Missing Explorer configuration: " + ", ".join(missing))
        return cls(
            origin=os.environ["C1_EXPLORER_ORIGIN"],
            client_id=get("C1_EXPLORER_CLIENT_ID", "c1-explorer"),
            client_secret=secret_value("C1_EXPLORER_CLIENT_SECRET") or "",
            session_idle_s=int(get("C1_EXPLORER_SESSION_IDLE_S", "1800")),
            session_max_s=int(get("C1_EXPLORER_SESSION_MAX_S", "28800")),
        )
