"""Live external OIDC enrollment uses Hydra's signed tokens and a real browser."""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, quote, urlsplit

import httpx
from playwright.sync_api import sync_playwright

from c1.authorization.principal import Principal
from tests.integration.m14c.conftest import External


def test_t01_t02_t04_t05_t07_t09_external_browser(external: External) -> None:
    origin = external.env["C1_EXPLORER_ORIGIN"]
    with httpx.Client(trust_env=False, timeout=30) as client:
        assert client.get(origin + "/v1/readyz").status_code == 503
        assert client.get(origin + "/v1/instance").status_code == 503
        assert client.get(origin + "/explorer/entities").status_code == 503
        assert client.get(origin + "/explorer/static/explorer.css").status_code == 200
        for grant in ("password", "client_credentials", "implicit"):
            response = client.post(
                "http://127.0.0.1:29090/oauth2/token",
                auth=(
                    external.env["C1_EXPLORER_CLIENT_ID"],
                    external.env["C1_EXPLORER_CLIENT_SECRET"],
                ),
                data={"grant_type": grant},
            )
            assert response.status_code == 400
        for response_type in ("token", "id_token", "code id_token"):
            refused = client.get(
                external.env["C1_ISSUER"] + "/oauth2/auth",
                params={
                    "client_id": external.env["C1_EXPLORER_CLIENT_ID"],
                    "response_type": response_type,
                    "scope": "openid",
                    "redirect_uri": origin + "/explorer/callback",
                    "state": "unsupported-grant-check",
                    "nonce": "unsupported-grant-check",
                    "code_challenge": "x" * 43,
                    "code_challenge_method": "S256",
                },
            )
            redirected = parse_qs(urlsplit(refused.headers.get("location", "")).query)
            redirected.update(parse_qs(urlsplit(refused.headers.get("location", "")).fragment))
            assert refused.status_code == 400 or (
                refused.status_code in {302, 303}
                and "error" in redirected
                and not any(key in redirected for key in ("code", "access_token", "id_token"))
            ), {"status": refused.status_code, "error": redirected.get("error")}
    external.operator(
        "enrollment-approve",
        "--issuer",
        external.env["C1_ISSUER"],
        "--subject",
        "external|approved",
        "--operator",
        "synthetic-operator",
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        wrong = browser.new_page()
        wrong.goto(origin + "/explorer/login")
        wrong.get_by_label("User", exact=True).fill("other")
        wrong.get_by_label("Password", exact=True).fill("synthetic-test-password")
        wrong.get_by_role("button", name="Sign in", exact=True).click()
        wrong.wait_for_url("**/explorer/callback?**")
        assert "Sign-in failed" in wrong.content()
        wrong.close()
        page = browser.new_page()
        page.goto(origin + "/explorer/login")
        page.get_by_label("User", exact=True).fill("approved")
        page.get_by_label("Password", exact=True).fill("synthetic-test-password")
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.get_by_role("button", name="Confirm enrollment", exact=True).wait_for()
        with httpx.Client(trust_env=False, timeout=30) as client:
            assert client.get(origin + "/v1/readyz").status_code == 503
        page.get_by_role("button", name="Confirm enrollment", exact=True).click()
        page.wait_for_url(origin + "/explorer/")
        assert "Confirm C1 administration" not in page.content()
        with httpx.Client(trust_env=False, timeout=30) as client:
            assert client.get(origin + "/v1/readyz").status_code == 200
        # The signed-in Explorer reaches ordinary application pages via the
        # same bearer boundary; enrollment does not create content bypasses.
        page.goto(origin + "/explorer/scopes")
        assert "The service is not ready" not in page.content()
        page.close()
        browser.close()
    admin_tokens = external.user_tokens("approved")
    other_tokens = external.user_tokens("other")
    with httpx.Client(base_url=origin, trust_env=False, timeout=60) as client:
        admin = {"Authorization": "Bearer " + admin_tokens["access_token"]}
        other = {"Authorization": "Bearer " + other_tokens["access_token"]}
        assert client.get("/v1/whoami", headers=admin).json()["subject"] == "external|approved"
        assert (
            client.get(
                "/v1/whoami", headers={"Authorization": "Bearer " + admin_tokens["id_token"]}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/v1/access-scopes", headers=other, json={"label": "Forbidden scope"}
            ).status_code
            == 403
        )
        scope_response = client.post(
            "/v1/access-scopes", headers=admin, json={"label": "External reviewed knowledge"}
        )
        assert scope_response.status_code == 201
        scope = scope_response.json()["id"]
        admin_id = Principal("external", "external|approved", "human").id
        other_id = Principal("external", "external|other", "human").id
        for member, roles in [
            (admin_id, ("reader", "creator", "contributor", "reviewer")),
            (other_id, ("reader", "reviewer")),
        ]:
            for role in roles:
                granted = client.post(
                    f"/v1/access-scopes/{scope}/members",
                    headers=admin,
                    json={"member": member, "role": role},
                )
                assert granted.status_code == 200
        from tests.integration.m03.conftest import entity_record

        identifier = external.env["C1_INSTANCE_IRI_BASE"] + "entity/" + str(uuid.uuid4())
        record = entity_record(identifier, label="External reviewed entity").model_dump(mode="json")
        base = client.get("/v1/instance", headers=admin).json()["knowledge_revision"]
        proposal = client.post(
            "/v1/changesets",
            headers={**admin, "Idempotency-Key": uuid.uuid4().hex},
            json={
                "base_revision": base,
                "rationale": "External OIDC workflow",
                "operations": [{"kind": "create", "record": record, "scope_id": scope}],
            },
        )
        assert proposal.status_code == 201
        changeset = proposal.json()["id"]
        submitted = client.post(f"/v1/changesets/{changeset}/submit", headers=admin)
        assert submitted.status_code == 200
        if submitted.json()["state"] == "submitted":
            validated = client.post(f"/v1/changesets/{changeset}/validate", headers=admin)
            assert validated.status_code == 200 and validated.json()["state"] == "validated"
        current = client.get(f"/v1/changesets/{changeset}", headers=admin).json()
        if current["state"] != "validated":
            report = client.get(f"/v1/changesets/{changeset}/validation", headers=admin).json()
            raise AssertionError(
                str({"state": current["state"], "diagnostics": report.get("diagnostics")})
            )
        self_approval = client.post(f"/v1/changesets/{changeset}/approve", headers=admin)
        assert self_approval.status_code == 403
        approved = client.post(f"/v1/changesets/{changeset}/approve", headers=other)
        assert approved.status_code == 200 and approved.json()["state"] == "approved"
        applied = client.post(
            f"/v1/changesets/{changeset}/apply",
            headers={**admin, "Idempotency-Key": uuid.uuid4().hex},
        )
        assert applied.status_code == 200 and applied.json()["state"] == "applied", applied.text
        resource = "/v1/resources/" + quote(identifier, safe="")
        assert client.get(resource, headers=other).status_code == 200
        context = client.post(
            "/v1/context",
            headers=other,
            json={
                "profile": "graph-context",
                "profile_version": "1",
                "anchor": {"id": identifier},
            },
        )
        assert context.status_code == 200
        assert "External reviewed entity" in context.json()["markdown"]
        record["properties"]["http://www.w3.org/2004/02/skos/core#prefLabel"][0]["lexical"] = (
            "External reviewed modification"
        )
        modified = client.post(
            "/v1/changesets",
            headers={**admin, "Idempotency-Key": uuid.uuid4().hex},
            json={
                "base_revision": client.get("/v1/instance", headers=admin).json()[
                    "knowledge_revision"
                ],
                "rationale": "Explicit external-user modification",
                "operations": [
                    {
                        "kind": "replace",
                        "resource_id": identifier,
                        "record": record,
                        "reason": "Reviewed correction",
                    }
                ],
            },
        )
        assert modified.status_code == 201
        change = modified.json()["id"]
        result = client.post(f"/v1/changesets/{change}/submit", headers=admin)
        if result.json()["state"] == "submitted":
            result = client.post(f"/v1/changesets/{change}/validate", headers=admin)
        assert result.status_code == 200 and result.json()["state"] == "validated"
        reviewed = client.post(f"/v1/changesets/{change}/approve", headers=other)
        assert reviewed.status_code == 200
        result = client.post(
            f"/v1/changesets/{change}/apply", headers={**admin, "Idempotency-Key": uuid.uuid4().hex}
        )
        assert result.status_code == 200 and result.json()["state"] == "applied"
        observed = client.get(resource, headers=other)
        assert observed.status_code == 200 and "External reviewed modification" in observed.text
        revoked = client.delete(
            f"/v1/access-scopes/{scope}/members/{quote(other_id, safe='')}",
            headers=admin,
            params={"role": "reader"},
        )
        assert revoked.status_code == 200
        assert client.get(resource, headers=other).status_code == 404
    external.operator(
        "enrollment-approve",
        "--issuer",
        external.env["C1_ISSUER"],
        "--subject",
        "external|other",
        "--operator",
        "synthetic-operator",
        expected=2,
    )
