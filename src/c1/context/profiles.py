"""Schema-validated context profiles from the trusted local catalog only."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from c1.model.diagnostics import fail
from c1.model.ids import validate_iri

Section = Literal[
    "interpretation", "orientation", "facts", "text", "disagreements", "gaps", "sources", "bounds"
]
SECTIONS: list[Section] = [
    "interpretation",
    "orientation",
    "facts",
    "text",
    "disagreements",
    "gaps",
    "sources",
    "bounds",
]
_FIELD = re.compile(r"[a-z][a-z0-9_]{0,127}\Z")


def _iris(values: list[str]) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError("IRIs must be unique")
    return [validate_iri(value) for value in values]


class PathStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    predicate: str
    direction: Literal["out", "in"]
    target_types: list[str] = Field(default_factory=list)

    @field_validator("predicate")
    @classmethod
    def check_predicate(cls, value: str) -> str:
        return validate_iri(value)

    @field_validator("target_types")
    @classmethod
    def check_types(cls, values: list[str]) -> list[str]:
        return _iris(values)


class ContextPath(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    steps: list[PathStep] = Field(min_length=1, max_length=3)
    max_depth: int = Field(ge=1, le=3)

    @model_validator(mode="after")
    def check_depth(self) -> Self:
        if len(self.steps) > self.max_depth:
            raise ValueError("path steps exceed max_depth")
        return self


class ContextProfile(BaseModel):
    """Declarative typed paths; no executable or free-text template fields."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    version: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+){0,2}$", max_length=32)
    anchor_types: list[str] = Field(min_length=1, max_length=100)
    target_types: list[str] = Field(min_length=1, max_length=100)
    topic_scheme: str
    topic_predicate: str
    topic_expand: Literal["off", "narrower"] = "off"
    paths: list[ContextPath] = Field(min_length=1, max_length=100)
    fact_predicates: list[str] | Literal["declared"]
    qualifier_predicates: list[str] = Field(default_factory=list)
    measurement_predicate: str | None = None
    document_source_predicate: str = "http://purl.org/dc/terms/source"
    required_qualifiers: dict[str, list[str]] = Field(default_factory=dict)
    role_types: dict[str, list[str]] = Field(default_factory=dict)
    conflict_basis: Literal["declared"] = "declared"
    fields: dict[str, str | ContextPath] = Field(default_factory=dict)
    group_by: Literal["node"] = "node"
    order: Literal["distance,label,id"] = "distance,label,id"
    sections: list[Section] = Field(default_factory=lambda: list(SECTIONS))

    @field_validator("anchor_types", "target_types", "qualifier_predicates")
    @classmethod
    def check_iris(cls, values: list[str]) -> list[str]:
        return _iris(values)

    @field_validator("topic_scheme", "topic_predicate", "document_source_predicate")
    @classmethod
    def check_iri(cls, value: str) -> str:
        return validate_iri(value)

    @field_validator("measurement_predicate")
    @classmethod
    def check_measurement_predicate(cls, value: str | None) -> str | None:
        return validate_iri(value) if value is not None else None

    @field_validator("required_qualifiers")
    @classmethod
    def check_required_qualifiers(cls, values: dict[str, list[str]]) -> dict[str, list[str]]:
        return {
            validate_iri(predicate): _iris(qualifiers) for predicate, qualifiers in values.items()
        }

    @field_validator("role_types")
    @classmethod
    def check_role_types(cls, values: dict[str, list[str]]) -> dict[str, list[str]]:
        if any(_FIELD.fullmatch(name) is None for name in values):
            raise ValueError("invalid profile role name")
        return {name: _iris(types) for name, types in values.items()}

    @model_validator(mode="after")
    def check_qualifier_declarations(self) -> Self:
        declared = set(self.qualifier_predicates)
        if any(set(required) - declared for required in self.required_qualifiers.values()):
            raise ValueError("required qualifiers must be declared qualifier predicates")
        if isinstance(self.fact_predicates, list) and set(self.required_qualifiers) - set(
            self.fact_predicates
        ):
            raise ValueError("required qualifier quantities must be declared fact predicates")
        return self

    @field_validator("fact_predicates")
    @classmethod
    def check_facts(cls, value: list[str] | Literal["declared"]) -> list[str] | Literal["declared"]:
        return _iris(value) if isinstance(value, list) else value

    @field_validator("fields")
    @classmethod
    def check_fields(cls, values: dict[str, str | ContextPath]) -> dict[str, str | ContextPath]:
        for name, value in values.items():
            if _FIELD.fullmatch(name) is None:
                raise ValueError("invalid profile field name")
            if isinstance(value, str):
                validate_iri(value)
        return values

    @field_validator("sections")
    @classmethod
    def check_sections(cls, value: list[Section]) -> list[Section]:
        if value != SECTIONS:
            raise ValueError("sections must use the fixed context template order")
        return value


SoftwareSection = Literal[
    "interpretation",
    "target",
    "normative",
    "implementation",
    "interfaces",
    "tests",
    "runs",
    "fixtures",
    "instructions",
    "discrepancies",
    "gaps",
    "sources",
    "bounds",
]
SOFTWARE_SECTIONS: list[SoftwareSection] = [
    "interpretation",
    "target",
    "normative",
    "implementation",
    "interfaces",
    "tests",
    "runs",
    "fixtures",
    "instructions",
    "discrepancies",
    "gaps",
    "sources",
    "bounds",
]
EvidenceRole = Literal["normative", "structural", "interpretive", "observed", "instruction"]
# Every unit kind the test-development stage can produce needs a declared role.
SOFTWARE_UNIT_KINDS = frozenset(
    {
        "documentation-part",
        "contract-part",
        "code-unit",
        "dependency-unit",
        "operation",
        "test-definition",
        "test-run",
        "fixture-unit",
        "instruction-part",
        "discrepancy",
    }
)


class SoftwareTask(BaseModel):
    """Bounded, declarative software-task selection; no templates or code."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    task: Literal["test-development"]
    requires_target: Literal[True] = True
    requires_goal: Literal[True] = True
    anchor_kinds: list[Literal["symbol", "capability", "operation"]] = Field(
        min_length=1, max_length=3
    )
    dependency_depth: int = Field(ge=0, le=1)
    max_dependencies: int = Field(ge=0, le=20)
    max_tests: int = Field(ge=1, le=50)
    max_runs: int = Field(ge=1, le=100)
    role_map: dict[str, EvidenceRole]
    sections: list[SoftwareSection] = Field(default_factory=lambda: list(SOFTWARE_SECTIONS))

    @model_validator(mode="after")
    def check_task(self) -> Self:
        if len(self.anchor_kinds) != len(set(self.anchor_kinds)):
            raise ValueError("anchor kinds must be unique")
        if set(self.role_map) != SOFTWARE_UNIT_KINDS:
            raise ValueError("role_map must declare exactly the software unit kinds")
        if self.sections != SOFTWARE_SECTIONS:
            raise ValueError("sections must use the fixed test-development template order")
        return self


class SoftwareContextProfile(BaseModel):
    """A software-task context profile; graph paths are not used in this mode."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    version: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+){0,2}$", max_length=32)
    software: SoftwareTask

    # Uniform catalog/listing surface shared with graph profiles.
    @property
    def fields(self) -> dict[str, str]:
        return {}


AnyContextProfile = ContextProfile | SoftwareContextProfile


def profile_digest(profile: AnyContextProfile) -> str:
    payload = json.dumps(
        profile.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_any_context_profile(path: Path) -> AnyContextProfile:
    """Read an explicit local file; never resolve imports or remote contexts."""
    if path.is_symlink() or not path.is_file() or path.suffix != ".json":
        fail("C1-CX-002", "Expected a local context profile JSON file", str(path))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Exactly one mode per profile: a `software` block selects the task kind.
        if isinstance(raw, dict) and "software" in raw:
            return SoftwareContextProfile.model_validate(raw)
        return ContextProfile.model_validate(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        fail("C1-CX-002", f"Invalid context profile: {type(exc).__name__}", str(path))


def load_context_profile(path: Path) -> ContextProfile:
    """A graph-context profile; any other kind is rejected."""
    profile = load_any_context_profile(path)
    if not isinstance(profile, ContextProfile):
        fail("C1-CX-002", "Expected a graph context profile", str(path))
    return profile


def _catalog_root() -> Path:
    package = Path(__file__).resolve().parents[1] / "profiles" / "context"
    repository = Path(__file__).resolve().parents[3] / "profiles" / "context"
    root = package if package.is_dir() else repository
    if root.is_symlink() or not root.is_dir():
        fail("C1-CX-002", "Trusted context profile catalog is unavailable")
    return root


class ContextProfileCatalog:
    """Exact profile/version selection from an eagerly validated local catalog."""

    def __init__(self) -> None:
        self.profiles: dict[tuple[str, str], AnyContextProfile] = {}
        root = _catalog_root()
        for path in sorted(root.iterdir()):
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                fail("C1-CX-002", "Unsupported context catalog entry", str(path))
            profile = load_any_context_profile(path)
            key = (profile.name, profile.version)
            if key in self.profiles:
                fail("C1-CX-002", "Duplicate context profile name and version", str(path))
            self.profiles[key] = profile
        if not self.profiles:
            fail("C1-CX-002", "Trusted context profile catalog is empty")

    def get_any(self, name: str, version: str) -> AnyContextProfile:
        profile = self.profiles.get((name, version))
        if profile is None:
            fail("C1-CX-002", "Context profile version is not in the trusted local catalog")
        return profile

    def get(self, name: str, version: str) -> ContextProfile:
        """A graph-context profile; software-task profiles use `get_any`."""
        profile = self.get_any(name, version)
        if not isinstance(profile, ContextProfile):
            fail("C1-CX-002", "Context profile is not a graph context profile")
        return profile

    def digest(self, name: str, version: str) -> str:
        return profile_digest(self.get_any(name, version))

    def catalog(self) -> list[dict[str, object]]:
        return [
            {
                "name": profile.name,
                "version": profile.version,
                "digest": profile_digest(profile),
                "anchor_types": profile.anchor_types
                if isinstance(profile, ContextProfile)
                else sorted(profile.software.anchor_kinds),
                "fields": sorted(profile.fields),
            }
            for _, profile in sorted(self.profiles.items())
        ]
