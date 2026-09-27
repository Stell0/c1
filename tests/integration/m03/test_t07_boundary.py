"""M03-T07: clients cannot select trusted authorities or smuggle policy data."""

from __future__ import annotations

import asyncio
import json

import httpx
import jwt

from c1.authorization.fga import resource_object, scope_object
from c1.model.nodes import NodeRecord
from scripts.stack import compose, wait_ready
from tests.integration.m03.conftest import C1, bearer, entity_record, live_case, resource_path


def test_t07_untrusted_selectors_grants_and_scope_fields_are_rejected() -> None:
    async def run() -> None:
        async with live_case() as case:
            scope = await case.scope("M03-T07 boundary")
            await case.grant(scope, "alice", "reader")
            record = entity_record(label="Selector test")
            await case.provision(record, scope)
            path = resource_path(record.id)
            assert (await case.request("GET", path, actor="alice")).status_code == 200

            for selector in ("database", "repository", "store", "issuer", "principal"):
                response = await case.request("GET", path + f"?{selector}=attacker", actor="alice")
                assert response.status_code == 400, (selector, response.text)
            for header in ("X-C1-Database", "X-Store", "X-Principal"):
                response = await case.request(
                    "GET", path, actor="alice", headers={header: "attacker"}
                )
                assert response.status_code == 400, (header, response.text)
            repeated = await case.request("GET", path + "?revision=x&revision=y", actor="alice")
            assert repeated.status_code == 400, repeated.text

            body = {"record": record.model_dump(mode="json"), "scope_id": scope}
            for field in ("access_scope_id", "bound_to", "grants"):
                response = await case.request(
                    "POST", "/v1/probe/resources", json={**body, field: "attacker"}
                )
                assert response.status_code == 400, (field, response.text)
                poisoned = entity_record(label="Poisoned")
                poisoned.properties[C1 + field] = ["urn:c1:scope:attacker"]
                response = await case.request(
                    "POST",
                    "/v1/probe/resources",
                    json={"record": poisoned.model_dump(mode="json"), "scope_id": scope},
                )
                assert response.status_code == 400, (field, response.text)
            assert (await case.request("GET", path, actor="alice")).status_code == 200

    asyncio.run(run())


def test_t07_provision_collision_never_reveals_hidden_identity() -> None:
    async def run() -> None:
        async with live_case() as case:
            original = await case.scope("M03-T07 original")
            destination = await case.scope("M03-T07 destination")
            existing = entity_record(label="Protected collision")
            fresh = entity_record(label="Fresh candidate")
            await case.provision(existing, original)

            async def state() -> tuple[object, ...]:
                tuples = set()
                for obj in (
                    scope_object(original),
                    scope_object(destination),
                    resource_object(existing.id),
                    resource_object(fresh.id),
                    "instance:" + case.settings.instance_id,
                ):
                    tuples.update(await case.fga.read(object=obj))
                return (
                    await case.journal.head(),
                    await case.knowledge.head(),
                    await case.journal.list("Operation"),
                    await case.journal.list("Binding"),
                    await case.knowledge.get_record(existing.id, case.runtime.registry),
                    await case.knowledge.get_record(fresh.id, case.runtime.registry),
                    tuples,
                )

            async def attempt(record: NodeRecord) -> httpx.Response:
                return await case.request(
                    "POST",
                    "/v1/probe/resources",
                    actor="bob",
                    json={
                        "record": record.model_dump(mode="json"),
                        "scope_id": destination,
                    },
                )

            before = await state()
            denied_existing = await attempt(existing)
            assert denied_existing.status_code == 403, denied_existing.text
            assert await state() == before
            denied_fresh = await attempt(fresh)
            assert denied_fresh.status_code == 403, denied_fresh.text
            assert denied_fresh.json() == denied_existing.json()
            assert await state() == before

            await case.grant(destination, "bob", "creator")
            assert (
                await case.request("GET", resource_path(existing.id), actor="bob")
            ).status_code == 404
            before = await state()
            hidden_collision = await attempt(existing)
            assert hidden_collision.status_code == 404, hidden_collision.text
            assert await state() == before

            await case.grant(original, "bob", "reader")
            assert (
                await case.request("GET", resource_path(existing.id), actor="bob")
            ).status_code == 200
            before = await state()
            visible_collision = await attempt(existing)
            assert visible_collision.status_code == 409, visible_collision.text
            assert await state() == before

    asyncio.run(run())


def test_t07_real_openfga_and_keycloak_outages_fail_closed() -> None:
    async def run() -> None:
        async with live_case() as case:
            scope = await case.scope("M03-T07 outage")
            await case.grant(scope, "alice", "reader")
            alice = await case.token("alice")
            record = entity_record(label="Outage boundary")
            await case.provision(record, scope)
            path = resource_path(record.id)
            assert (await case.request("GET", path, actor="alice")).status_code == 200

            try:
                await asyncio.to_thread(compose, ["stop", "openfga"])
                denied = await case.request("GET", path, actor="alice")
                assert denied.status_code in (404, 503), denied.text
                assert denied.json().get("detail") != record.properties
                mutation = await case.request(
                    "POST",
                    f"/v1/access-scopes/{scope}/members",
                    json={"member": (await case.principal("bob")).id, "role": "reader"},
                )
                assert mutation.status_code == 503, mutation.text
                assert (await case.client.get("/v1/readyz")).status_code == 503
            finally:
                await asyncio.to_thread(compose, ["start", "openfga"])
                await asyncio.to_thread(wait_ready)
            assert (await case.request("GET", path, actor="alice")).status_code == 200

            # The already-trusted key may validate an issued token while the
            # issuer is offline; an unknown key and readiness must fail closed.
            header, payload, signature = alice.split(".")
            changed = jwt.get_unverified_header(alice)
            changed["kid"] = "unknown-m03-key"
            unknown_header = jwt.utils.base64url_encode(
                json.dumps(changed, separators=(",", ":")).encode()
            ).decode()
            unknown_kid = ".".join((unknown_header, payload, signature))
            assert unknown_header != header
            try:
                await asyncio.to_thread(compose, ["stop", "keycloak"])
                assert (
                    await case.client.get("/v1/whoami", headers=bearer(alice))
                ).status_code == 200
                assert (
                    await case.client.get("/v1/whoami", headers=bearer(unknown_kid))
                ).status_code == 401
                assert (await case.client.get("/v1/readyz")).status_code == 503
            finally:
                await asyncio.to_thread(compose, ["start", "keycloak"])
                await asyncio.to_thread(wait_ready)
            assert (await case.client.get("/v1/readyz")).status_code == 200

    asyncio.run(run())
