"""Explorer pages (M12 D6). Every handler reads and writes only through ``ctx.api``.

Buttons and forms appear according to API answers, but visibility is never
authorization: every action is decided by the C1 API (D6).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from starlette.responses import RedirectResponse, Response

from c1.explorer.app import Ctx, problem_text, secured
from c1.explorer.client import ApiFailure, path_id
from c1.explorer.render import query
from c1.explorer.security import FormError
from c1.model.keywords import NORMALIZATION_VERSION, normalize
from c1.model.literals import LiteralValue
from c1.model.nodes import NodeRecord
from c1.model.records import AssertionRecord, EntityRecord, EvidenceRecord, SourceRecord

C1 = "urn:c1:ns:core#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XSD = "http://www.w3.org/2001/XMLSchema#"
XSD_STRING = XSD + "string"
RDF_LANG = RDF + "langString"
SKOS_PREF = "http://www.w3.org/2004/02/skos/core#prefLabel"
SKOS_ALT = "http://www.w3.org/2004/02/skos/core#altLabel"
DOCUMENT = C1 + "Document"
DOCUMENT_PART = C1 + "DocumentPart"
ASSERTION = C1 + "Assertion"
STANDARD_ENTITY_PROPERTIES = {
    SKOS_PREF,
    SKOS_ALT,
    "http://purl.org/dc/terms/description",
    C1 + "keyword",
    C1 + "lifecycle",
    C1 + "projectReference",
    C1 + "provisionedScopeHint",
}
CHANGESET_ACTIONS = {"submit", "validate", "approve", "reject", "apply", "withdraw", "rebase"}
SCOPE_ROLES = ("reader", "contributor", "creator", "reviewer", "access_admin")
INSTANCE_ROLES = ("schema_admin", "access_admin", "operator")
ENTITY_FILTERS = (
    "types",
    "label",
    "label_mode",
    "alias",
    "alias_mode",
    "keywords_any",
    "keywords_all",
    "project_ref",
    "valid_at",
    "include_unknown",
    "lifecycle",
    "review_state",
    "revision",
    "order",
    "limit",
    "cursor",
)


def redirect(path: str) -> Response:
    return secured(RedirectResponse(path, status_code=303))


def _literal(text: str, language: str = "") -> LiteralValue:
    if language:
        return LiteralValue(lexical=text, datatype=RDF_LANG, language=language)
    return LiteralValue(lexical=text, datatype=XSD_STRING)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


async def _instance(ctx: Ctx) -> dict[str, Any]:
    response = await ctx.api("GET", "/v1/instance")
    if not response.ok or not isinstance(response.body, dict):
        raise ApiFailure(response)
    return response.body


def _new_id(instance: dict[str, Any], kind: str) -> str:
    return f"{instance['instance_base']}{kind}/{uuid.uuid4()}"


async def _scopes(ctx: Ctx, *roles: str) -> list[dict[str, Any]]:
    response = await ctx.api("GET", "/v1/access-scopes/mine")
    if not response.ok or not isinstance(response.body, dict):
        return []
    return [
        scope
        for scope in response.body.get("access_scopes", [])
        if not roles or set(roles) & set(scope.get("roles", []))
    ]


async def _schema(ctx: Ctx) -> dict[str, Any]:
    response = await ctx.api("GET", "/v1/schema")
    return response.body if response.ok and isinstance(response.body, dict) else {"profiles": []}


def _entity_classes(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Classes the API treats as entities: core Entity or a profile class of kind entity."""
    classes = []
    for profile in schema.get("profiles", []):
        for item in profile.get("classes", []):
            if item["iri"] == C1 + "Entity" or item.get("kind") == "entity":
                classes.append({**item, "profile": profile["name"]})
    return classes


def _predicates(schema: dict[str, Any]) -> list[str]:
    result: set[str] = set()
    for profile in schema.get("profiles", []):
        for item in profile.get("classes", []):
            for prop in item.get("properties", []):
                result.add(prop["iri"])
    return sorted(result)


# --- Reading ---------------------------------------------------------------


async def home(ctx: Ctx) -> Response:
    whoami = await ctx.api("GET", "/v1/whoami")
    catalog = await ctx.api("GET", "/v1/catalog")
    ready = await ctx.api("GET", "/v1/readyz")
    return await ctx.page(
        "home.html",
        whoami=whoami.body if whoami.ok else None,
        catalog=catalog.body if catalog.ok else None,
        catalog_status=catalog.status,
        ready=ready.ok,
    )


async def entities(ctx: Ctx) -> Response:
    filters = {name: ctx.arg(name) for name in ENTITY_FILTERS}
    searched = any(filters[name] for name in ENTITY_FILTERS if name not in {"order", "limit"})
    params = {k: v for k, v in filters.items() if v}
    response = await ctx.api("GET", "/v1/entities", params=params)
    if not response.ok:
        return await ctx.problem(response, title="Entities")
    return await ctx.page("entities.html", filters=filters, result=response.body, searched=searched)


async def resource(ctx: Ctx) -> Response:
    identifier = ctx.arg("id")
    revision = ctx.arg("revision")
    if not identifier:
        raise FormError("missing_field")
    response = await ctx.api(
        "GET", "/v1/resources/" + path_id(identifier), params={"revision": revision}
    )
    if not response.ok:
        return await ctx.problem(response, title="Resource")
    record = response.body
    types = record.get("types", []) if isinstance(record, dict) else []
    if DOCUMENT in types and not revision:
        return redirect(query("/explorer/document", id=identifier))
    about: Any = None
    mentions: Any = None
    if ASSERTION not in types:
        about_response = await ctx.api(
            "GET", "/v1/assertions", params={"subject": identifier, "revision": revision}
        )
        about = about_response.body if about_response.ok else None
        mention_response = await ctx.api(
            "GET", "/v1/assertions", params={"object": identifier, "revision": revision}
        )
        mentions = mention_response.body if mention_response.ok else None
    return await ctx.page(
        "resource.html",
        record=record,
        revision=revision,
        about=about,
        mentions=mentions,
        is_assertion=ASSERTION in types,
        is_entity=C1 + "Entity" in types or SKOS_PREF in (record.get("properties") or {}),
    )


async def competing(ctx: Ctx) -> Response:
    subject, predicate = ctx.arg("subject"), ctx.arg("predicate")
    if not subject or not predicate:
        raise FormError("missing_field")
    response = await ctx.api(
        "GET",
        "/v1/assertions",
        params={"competing_for": subject + "," + predicate, "revision": ctx.arg("revision")},
    )
    if not response.ok:
        return await ctx.problem(response, title="Competing claims")
    return await ctx.page(
        "competing.html", subject=subject, predicate=predicate, result=response.body
    )


async def neighborhood(ctx: Ctx) -> Response:
    identifier = ctx.arg("id")
    if not identifier:
        raise FormError("missing_field")
    form = {
        "direction": ctx.arg("direction", "both"),
        "predicates": ctx.arg("predicates"),
        "depth": ctx.arg("depth", "1"),
        "revision": ctx.arg("revision"),
        "cursor": ctx.arg("cursor"),
    }
    result = None
    if form["predicates"]:
        response = await ctx.api(
            "GET", f"/v1/entities/{path_id(identifier)}/neighborhood", params=form
        )
        if not response.ok:
            return await ctx.problem(response, title="Neighborhood")
        result = response.body
    schema = await _schema(ctx)
    return await ctx.page(
        "neighborhood.html",
        identifier=identifier,
        form=form,
        result=result,
        predicates=_predicates(schema),
    )


async def history(ctx: Ctx) -> Response:
    identifier = ctx.arg("id")
    if not identifier:
        raise FormError("missing_field")
    response = await ctx.api(
        "GET",
        "/v1/history",
        params={"resource_id": identifier, "cursor": ctx.arg("cursor"), "limit": "20"},
    )
    if not response.ok:
        return await ctx.problem(response, title="History")
    return await ctx.page("history.html", identifier=identifier, result=response.body)


async def documents(ctx: Ctx) -> Response:
    form = {
        "title": ctx.arg("title"),
        "text_contains": ctx.arg("text_contains"),
        "revision": ctx.arg("revision"),
        "cursor": ctx.arg("cursor"),
    }
    response = await ctx.api("GET", "/v1/documents", params=form)
    if not response.ok:
        return await ctx.problem(response, title="Documents")
    return await ctx.page("documents.html", form=form, result=response.body)


async def document(ctx: Ctx) -> Response:
    identifier = ctx.arg("id")
    revision = ctx.arg("revision")
    if not identifier:
        raise FormError("missing_field")
    detail = await ctx.api(
        "GET",
        "/v1/documents/by-id",
        params={"document_id": identifier, "revision": revision},
    )
    if not detail.ok:
        return await ctx.problem(detail, title="Document")
    return await ctx.page(
        "document.html", identifier=identifier, revision=revision, detail=detail.body
    )


async def document_source(ctx: Ctx) -> Response:
    identifier = ctx.arg("id")
    if not identifier:
        raise FormError("missing_field")
    fmt = ctx.arg("format", "markdown")
    if fmt not in {"markdown", "text"}:
        raise FormError("invalid_format")
    response = await ctx.api(
        "GET",
        f"/v1/documents/{path_id(identifier)}/render",
        params={"format": fmt, "revision": ctx.arg("revision")},
    )
    if not response.ok:
        return await ctx.problem(response, title="Document source")
    return await ctx.page(
        "document_source.html", identifier=identifier, fmt=fmt, result=response.body
    )


async def document_history(ctx: Ctx) -> Response:
    identifier = ctx.arg("id")
    if not identifier:
        raise FormError("missing_field")
    response = await ctx.api(
        "GET",
        f"/v1/documents/{path_id(identifier)}/history",
        params={"cursor": ctx.arg("cursor")},
    )
    if not response.ok:
        return await ctx.problem(response, title="Document history")
    return await ctx.page(
        "history.html", identifier=identifier, result=response.body, document=True
    )


async def schema(ctx: Ctx) -> Response:
    response = await ctx.api("GET", "/v1/schema")
    if not response.ok:
        return await ctx.problem(response, title="Schema")
    return await ctx.page("schema.html", schema=response.body)


# --- Context preview -----------------------------------------------------

CONTEXT_FIELDS = (
    "profile",
    "anchor_id",
    "anchor_label",
    "anchor_language",
    "topics",
    "keywords_any",
    "keywords_all",
    "fields",
    "project_ref",
    "revision",
    "budget",
    "snapshots",
    "contracts",
    "configurations",
    "goal",
    "aspects",
    "followup_token",
    "cursor",
)


def context_request(form: dict[str, str], catalog: dict[str, Any]) -> dict[str, Any]:
    """Build the strict ``POST /v1/context`` body from the preview form."""
    name, _, version = form["profile"].partition("@")
    if not name or not version:
        raise FormError("missing_field")
    body: dict[str, Any] = {"profile": name, "profile_version": version}
    if form["anchor_id"]:
        body["anchor"] = {"id": form["anchor_id"]}
    elif form["anchor_label"]:
        body["anchor"] = {"label": form["anchor_label"]}
        if form["anchor_language"]:
            body["anchor"]["language"] = form["anchor_language"]
    else:
        raise FormError("missing_field")
    for key in ("topics", "fields", "aspects"):
        values = _lines(form[key])
        if values:
            body[key] = values
    for key in ("keywords_any", "keywords_all"):
        values = _lines(form[key])
        if values:
            body[key] = [{"text": value} for value in values]
    for key in ("project_ref", "revision", "goal", "followup_token", "cursor"):
        if form[key]:
            body[key] = form[key]
    target = {
        key: _lines(form[key])
        for key in ("snapshots", "contracts", "configurations")
        if _lines(form[key])
    }
    if target:
        body["target"] = target
    if form["budget"]:
        try:
            body["budget"] = {"unit": "bytes", "maximum": int(form["budget"])}
        except ValueError:
            raise FormError("invalid_budget") from None
    body["formats"] = ["markdown", "structured"]
    return body


async def context(ctx: Ctx) -> Response:
    form = {name: ctx.arg(name) for name in CONTEXT_FIELDS}
    catalog_response = await ctx.api("GET", "/v1/catalog")
    catalog = catalog_response.body if catalog_response.ok else {}
    result: Any = None
    status = 200
    problem = None
    request_body = None
    if form["profile"]:
        request_body = context_request(form, catalog)
        response = await ctx.api("POST", "/v1/context", json=request_body)
        if response.ok:
            result = response.body
        else:
            status = response.status
            problem = {
                "status": response.status,
                "code": response.code,
                "detail": problem_text(response),
            }
    continuation = None
    if isinstance(result, dict):
        next_cursor = (result.get("bounds") or {}).get("next_cursor")
        if next_cursor:
            continuation = query("/explorer/context", **{**form, "cursor": next_cursor})
    return await ctx.page(
        "context.html",
        status=status if status >= 400 else 200,
        form=form,
        catalog=catalog,
        result=result,
        problem=problem,
        continuation=continuation,
        request_json=json.dumps(request_body, indent=2, sort_keys=True) if request_body else "",
    )


# --- Software ---------------------------------------------------------------


async def software(ctx: Ctx) -> Response:
    form = {
        "snapshots": ctx.arg("snapshots"),
        "contracts": ctx.arg("contracts"),
        "configurations": ctx.arg("configurations"),
        "capability_id": ctx.arg("capability_id"),
        "operation_id": ctx.arg("operation_id"),
        "symbol_id": ctx.arg("symbol_id"),
        "path_prefix": ctx.arg("path_prefix"),
        "revision": ctx.arg("revision"),
        "cursor": ctx.arg("cursor"),
    }
    resolved: Any = None
    lookup: Any = None
    problem = None
    target = {
        key: _lines(form[key])
        for key in ("snapshots", "contracts", "configurations")
        if _lines(form[key])
    }
    if target:
        body: dict[str, Any] = {"target": target}
        if form["revision"]:
            body["revision"] = form["revision"]
        response = await ctx.api("POST", "/v1/software/targets/resolve", json=body)
        if not response.ok:
            return await ctx.problem(response, title="Software target")
        resolved = response.body
        select = {
            key: form[key]
            for key in ("capability_id", "operation_id", "symbol_id", "path_prefix")
            if form[key]
        }
        lookup_body: dict[str, Any] = {"target": target, "limit": 50}
        if select:
            lookup_body["select"] = select
        if form["cursor"]:
            lookup_body["cursor"] = form["cursor"]
        if form["revision"]:
            lookup_body["revision"] = form["revision"]
        response = await ctx.api("POST", "/v1/software/lookup", json=lookup_body)
        if response.ok:
            lookup = response.body
        else:
            problem = {"status": response.status, "code": response.code}
    continuation = None
    if isinstance(lookup, dict) and lookup.get("next_cursor"):
        continuation = query("/explorer/software", **{**form, "cursor": lookup["next_cursor"]})
    return await ctx.page(
        "software.html",
        form=form,
        resolved=resolved,
        lookup=lookup,
        problem=problem,
        continuation=continuation,
    )


# --- ChangeSets -------------------------------------------------------------


async def changesets(ctx: Ctx) -> Response:
    response = await ctx.api("GET", "/v1/changesets")
    if not response.ok:
        return await ctx.problem(response, title="ChangeSets")
    return await ctx.page("changesets.html", result=response.body)


async def changeset(ctx: Ctx) -> Response:
    identifier = ctx.arg("id")
    if not identifier:
        raise FormError("missing_field")
    response = await ctx.api("GET", "/v1/changesets/" + path_id(identifier))
    if not response.ok:
        return await ctx.problem(response, title="ChangeSet")
    validation = None
    if isinstance(response.body, dict) and response.body.get("validation_report_id"):
        report = await ctx.api("GET", f"/v1/changesets/{path_id(identifier)}/validation")
        validation = report.body if report.ok else None
    whoami = await ctx.api("GET", "/v1/whoami")
    return await ctx.page(
        "changeset.html",
        changeset=response.body,
        validation=validation,
        operations_json=json.dumps(
            response.body.get("operations", []), indent=2, sort_keys=True, ensure_ascii=False
        ),
        whoami=whoami.body if whoami.ok else {},
    )


async def changeset_action(ctx: Ctx) -> Response:
    identifier = ctx.field("id")
    action = ctx.field("action")
    if action not in CHANGESET_ACTIONS:
        raise FormError("invalid_action")
    body: dict[str, Any] = {}
    key = None
    if action == "reject":
        body = {"reason": ctx.field("reason") or "Rejected in the Explorer"}
    elif action == "rebase":
        instance = await _instance(ctx)
        body = {"base_revision": instance["knowledge_revision"]}
    elif action == "apply":
        key = ctx.field("idempotency_key")
    response = await ctx.api(
        "POST",
        f"/v1/changesets/{path_id(identifier)}/{action}",
        json=body,
        idempotency_key=key,
    )
    if not response.ok:
        return await ctx.problem(response, title=f"ChangeSet {action}")
    return redirect(query("/explorer/changeset", id=identifier))


async def _create_changeset(ctx: Ctx, operations: list[dict[str, Any]], rationale: str) -> Response:
    instance = await _instance(ctx)
    body: dict[str, Any] = {
        "base_revision": instance["knowledge_revision"],
        "operations": operations,
    }
    if rationale:
        body["rationale"] = rationale
    response = await ctx.api(
        "POST", "/v1/changesets", json=body, idempotency_key=ctx.field("idempotency_key")
    )
    if not response.ok or not isinstance(response.body, dict):
        return await ctx.problem(response, title="New ChangeSet")
    return redirect(query("/explorer/changeset", id=str(response.body["id"])))


async def new_changeset(ctx: Ctx) -> Response:
    kind = ctx.arg("form", "entity")
    if kind not in {"entity", "names", "assertion", "profile"}:
        raise FormError("invalid_form")
    schema_body = await _schema(ctx)
    scopes = await _scopes(ctx, "creator", "contributor")
    record = None
    if kind == "names":
        identifier = ctx.arg("id")
        if not identifier:
            raise FormError("missing_field")
        response = await ctx.api("GET", "/v1/resources/" + path_id(identifier))
        if not response.ok:
            return await ctx.problem(response, title="Edit names and keywords")
        record = response.body
    classes = _entity_classes(schema_body)
    selected = next((c for c in classes if c["iri"] == ctx.arg("class")), None)
    return await ctx.page(
        "changeset_new.html",
        kind=kind,
        selected_class=selected,
        standard_properties=sorted(STANDARD_ENTITY_PROPERTIES),
        schema=schema_body,
        entity_classes=classes,
        predicates=_predicates(schema_body),
        scopes=scopes,
        record=record,
        subject=ctx.arg("subject"),
        idempotency_key=str(uuid.uuid4()),
    )


def _typed_value(lexical: str, datatype: str, language: str) -> LiteralValue | str:
    if datatype == "@id":
        return lexical
    if language:
        return LiteralValue(lexical=lexical, datatype=RDF_LANG, language=language)
    return LiteralValue(lexical=lexical, datatype=datatype or XSD_STRING)


async def create_entity(ctx: Ctx) -> Response:
    schema_body = await _schema(ctx)
    classes = {item["iri"]: item for item in _entity_classes(schema_body)}
    class_iri = ctx.field("class")
    if class_iri not in classes:
        raise FormError("invalid_class")
    language = ctx.field("language", required=False)
    label = ctx.field("label").strip()
    if not label:
        raise FormError("missing_field")
    instance = await _instance(ctx)
    description = ctx.field("description", required=False).strip()
    entity = EntityRecord(
        id=_new_id(instance, "entity"),
        types=[class_iri],
        labels=[_literal(label, language)],
        aliases=[
            _literal(alias, language) for alias in _lines(ctx.field("aliases", required=False))
        ],
        description=_literal(description, language) if description else None,
    ).to_node()
    properties: dict[str, list[Any]] = dict(entity.properties)
    for prop in classes[class_iri]["properties"]:
        if prop["iri"] in STANDARD_ENTITY_PROPERTIES:
            continue
        raw = ctx.field("p:" + prop["iri"], required=False).strip()
        if not raw:
            continue
        if prop["enum"] and raw not in prop["enum"]:
            raise FormError("invalid_enum")
        ranges = prop["ranges"]
        datatype = ctx.field("t:" + prop["iri"], required=False) or ranges[0]
        if datatype not in ranges:
            raise FormError("invalid_datatype")
        properties[prop["iri"]] = [_typed_value(raw, datatype, "")]
    record = {"id": entity.id, "types": entity.types, "properties": {}}
    record["properties"] = {
        key: [v.model_dump(mode="json") if isinstance(v, LiteralValue) else v for v in values]
        for key, values in properties.items()
    }
    operation = {"kind": "create", "record": record, "scope_id": ctx.field("scope")}
    return await _create_changeset(ctx, [operation], ctx.field("rationale", required=False))


async def edit_names(ctx: Ctx) -> Response:
    identifier = ctx.field("id")
    response = await ctx.api("GET", "/v1/resources/" + path_id(identifier))
    if not response.ok or not isinstance(response.body, dict):
        return await ctx.problem(response, title="Edit names and keywords")
    current = EntityRecord.from_node(NodeRecord.model_validate(response.body))
    language = ctx.field("language", required=False)
    aliases = [_literal(alias, language) for alias in _lines(ctx.field("aliases", required=False))]
    keep = set(ctx.fields("keep_keyword"))
    keywords = [iri for iri in current.keywords if iri in keep]
    instance = await _instance(ctx)
    operations: list[dict[str, Any]] = []
    for text in _lines(ctx.field("new_keywords", required=False)):
        keyword_id = _new_id(instance, "keyword")
        properties: dict[str, Any] = {
            C1 + "keywordText": [{"lexical": text, "datatype": XSD_STRING}],
            C1 + "normalizedKeyword": [{"lexical": normalize(text), "datatype": XSD_STRING}],
            C1 + "normalizationVersion": [
                {"lexical": NORMALIZATION_VERSION, "datatype": XSD_STRING}
            ],
        }
        if language:
            properties[C1 + "keywordLanguage"] = [{"lexical": language, "datatype": XSD_STRING}]
        operations.append(
            {
                "kind": "create",
                "record": {
                    "id": keyword_id,
                    "types": [C1 + "Keyword"],
                    "properties": properties,
                },
                "scope_id": ctx.field("scope"),
            }
        )
        keywords.append(keyword_id)
    updated = current.model_copy(update={"aliases": aliases, "keywords": keywords}).to_node()
    operations.append(
        {
            "kind": "replace",
            "resource_id": identifier,
            "record": updated.model_dump(mode="json"),
            "reason": ctx.field("reason", required=False) or "Edited names in the Explorer",
        }
    )
    return await _create_changeset(ctx, operations, ctx.field("rationale", required=False))


async def create_assertion(ctx: Ctx) -> Response:
    """One ChangeSet: a Source, an Evidence item and the assertion it supports."""
    instance = await _instance(ctx)
    scope = ctx.field("scope")
    source_id = _new_id(instance, "source")
    assertion_id = _new_id(instance, "assertion")
    evidence_id = _new_id(instance, "evidence")
    revision = ctx.field("source_revision").strip()
    excerpt = ctx.field("excerpt", required=False)
    locator = ctx.field("locator", required=False).strip()
    if not revision:
        raise FormError("missing_field")
    source = SourceRecord(
        id=source_id,
        title=_literal(ctx.field("source_title").strip()),
        kind=ctx.field("source_kind").strip() or "document",
        revision=revision,
        locator=LiteralValue(lexical=locator, datatype=XSD_STRING) if locator else None,
    ).to_node()
    evidence = EvidenceRecord(
        id=evidence_id,
        assertion_id=assertion_id,
        source_id=source_id,
        source_revision=revision,
        excerpt=_literal(excerpt) if excerpt else None,
    ).to_node()
    object_kind = ctx.field("object_kind")
    raw_object = ctx.field("object").strip()
    if not raw_object:
        raise FormError("missing_field")
    if object_kind == "iri":
        value: str | LiteralValue = raw_object
    elif object_kind == "literal":
        value = _typed_value(
            raw_object,
            ctx.field("object_datatype", required=False) or XSD_STRING,
            ctx.field("object_language", required=False),
        )
    else:
        raise FormError("invalid_object_kind")
    origin = ctx.field("origin")
    if origin not in {"manual", "imported"}:
        raise FormError("invalid_origin")
    assertion = AssertionRecord(
        id=assertion_id,
        subject=ctx.field("subject").strip(),
        predicate=ctx.field("predicate").strip(),
        object=value,
        origin=origin,  # type: ignore[arg-type]
        evidence_ids=[evidence_id],
    ).to_node()
    operations = [
        {"kind": "create", "record": item.model_dump(mode="json"), "scope_id": scope}
        for item in (source, evidence, assertion)
    ]
    return await _create_changeset(ctx, operations, ctx.field("rationale", required=False))


async def install_profile(ctx: Ctx) -> Response:
    operation = {"kind": "install_profile", "profile": ctx.field("profile")}
    return await _create_changeset(ctx, [operation], ctx.field("rationale", required=False))


# --- Access administration -------------------------------------------------


async def scopes(ctx: Ctx) -> Response:
    mine = await ctx.api("GET", "/v1/access-scopes/mine")
    administered = await ctx.api("GET", "/v1/access-scopes")
    if not mine.ok:
        return await ctx.problem(mine, title="Access scopes")
    return await ctx.page(
        "scopes.html",
        mine=mine.body.get("access_scopes", []) if isinstance(mine.body, dict) else [],
        administered=(
            administered.body.get("access_scopes", [])
            if administered.ok and isinstance(administered.body, dict)
            else []
        ),
        roles=SCOPE_ROLES,
        instance_roles=INSTANCE_ROLES,
    )


async def scope_create(ctx: Ctx) -> Response:
    body: dict[str, Any] = {"label": ctx.field("label")}
    if ctx.field("id", required=False):
        body["id"] = ctx.field("id")
    kind = ctx.field("kind", required=False) or "standard"
    if kind not in {"standard", "drafting"}:
        raise FormError("invalid_kind")
    body["kind"] = kind
    response = await ctx.api("POST", "/v1/access-scopes", json=body)
    if not response.ok:
        return await ctx.problem(response, title="Create scope")
    return redirect("/explorer/scopes")


async def scope_member(ctx: Ctx) -> Response:
    scope_id, member, role = ctx.field("scope"), ctx.field("member"), ctx.field("role")
    if role not in SCOPE_ROLES:
        raise FormError("invalid_role")
    grant = ctx.field("grant")
    if grant == "grant":
        response = await ctx.api(
            "POST",
            f"/v1/access-scopes/{path_id(scope_id)}/members",
            json={"member": member, "role": role},
        )
    elif grant == "revoke":
        response = await ctx.api(
            "DELETE",
            f"/v1/access-scopes/{path_id(scope_id)}/members/{path_id(member)}",
            params={"role": role},
        )
    else:
        raise FormError("invalid_action")
    if not response.ok:
        return await ctx.problem(response, title="Scope membership")
    return redirect("/explorer/scopes")


async def scope_retire(ctx: Ctx) -> Response:
    response = await ctx.api("DELETE", "/v1/access-scopes/" + path_id(ctx.field("scope")))
    if not response.ok:
        return await ctx.problem(response, title="Retire scope")
    return redirect("/explorer/scopes")


async def rescope(ctx: Ctx) -> Response:
    response = await ctx.api(
        "POST",
        f"/v1/access-scopes/{path_id(ctx.field('scope'))}/bindings",
        json={"resource_id": ctx.field("resource_id")},
    )
    if not response.ok or not isinstance(response.body, dict):
        return await ctx.problem(response, title="Propose re-scope")
    return redirect(query("/explorer/operation", id=str(response.body["id"])))


async def instance_grant(ctx: Ctx) -> Response:
    role = ctx.field("role")
    if role not in INSTANCE_ROLES:
        raise FormError("invalid_role")
    response = await ctx.api(
        "POST", "/v1/instance/grants", json={"member": ctx.field("member"), "role": role}
    )
    if not response.ok:
        return await ctx.problem(response, title="Instance grant")
    return redirect("/explorer/scopes")


async def operations(ctx: Ctx) -> Response:
    response = await ctx.api("GET", "/v1/security-operations")
    if not response.ok:
        return await ctx.problem(response, title="Security operations")
    return await ctx.page("operations.html", result=response.body)


async def operation(ctx: Ctx) -> Response:
    identifier = ctx.arg("id")
    if not identifier:
        raise FormError("missing_field")
    response = await ctx.api("GET", "/v1/security-operations/" + path_id(identifier))
    if not response.ok:
        return await ctx.problem(response, title="Security operation")
    return await ctx.page("operation.html", operation=response.body)


async def operation_action(ctx: Ctx) -> Response:
    identifier, action = ctx.field("id"), ctx.field("action")
    if action not in {"approve", "apply"}:
        raise FormError("invalid_action")
    response = await ctx.api(
        "POST", f"/v1/security-operations/{path_id(identifier)}/{action}", json={}
    )
    if not response.ok:
        return await ctx.problem(response, title=f"Security operation {action}")
    return redirect(query("/explorer/operation", id=identifier))


ROUTES: list[tuple[str, Any, bool]] = [
    ("/explorer/", home, False),
    ("/explorer/entities", entities, False),
    ("/explorer/resource", resource, False),
    ("/explorer/competing", competing, False),
    ("/explorer/neighborhood", neighborhood, False),
    ("/explorer/history", history, False),
    ("/explorer/documents", documents, False),
    ("/explorer/document", document, False),
    ("/explorer/document/source", document_source, False),
    ("/explorer/document/history", document_history, False),
    ("/explorer/schema", schema, False),
    ("/explorer/context", context, False),
    ("/explorer/software", software, False),
    ("/explorer/changesets", changesets, False),
    ("/explorer/changeset", changeset, False),
    ("/explorer/changesets/new", new_changeset, False),
    ("/explorer/changesets/entity", create_entity, True),
    ("/explorer/changesets/names", edit_names, True),
    ("/explorer/changesets/assertion", create_assertion, True),
    ("/explorer/changesets/profile", install_profile, True),
    ("/explorer/changeset/action", changeset_action, True),
    ("/explorer/scopes", scopes, False),
    ("/explorer/scopes/create", scope_create, True),
    ("/explorer/scopes/member", scope_member, True),
    ("/explorer/scopes/retire", scope_retire, True),
    ("/explorer/scopes/rescope", rescope, True),
    ("/explorer/instance/grant", instance_grant, True),
    ("/explorer/operations", operations, False),
    ("/explorer/operation", operation, False),
    ("/explorer/operation/action", operation_action, True),
]
