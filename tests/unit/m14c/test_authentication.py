"""M14c identity/profile compatibility and fail-closed endpoint trust."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from c1.authorization.principal import Principal
from c1.authorization.tokens import AuthenticationError, TokenValidator
from c1.oidc import trusted_endpoint
from tests.unit.m03.test_tokens import claims, oidc_server, sign


def test_subject_encoding_preserves_exact_identity_and_legacy_ids() -> None:
    subjects = ["abc", "abc.def", "ABC", "abc:def", "abc@def", "~YWJj", "a|b", "a/b", "a b"]
    principals = [Principal("provider", subject, "human") for subject in subjects]
    assert len({p.id for p in principals}) == len(subjects)
    assert principals[0].id == "user:provider.abc"
    assert principals[1].id == "user:provider.abc.def"
    assert principals[3].id == "user:provider.~YWJjOmRlZg"
    assert Principal("other", "abc:def", "human").id != principals[3].id
    assert Principal("provider", "abc:def", "service").id == principals[3].id
    for principal in principals:
        assert Principal.from_id(principal.id) == principal


@pytest.mark.parametrize(
    "identifier",
    [
        "user:provider.~YWJj",
        "user:provider.~",
        "user:provider.~YWJjOmRlZg==",
        "user:provider.~YWJjOmRlZh",
        "user:provider.~_w",
        "group:provider.abc",
    ],
)
def test_noncanonical_encoded_ids_are_rejected(identifier: str) -> None:
    with pytest.raises(ValueError):
        Principal.from_id(identifier)


@pytest.mark.parametrize("subject", ["", "a\nb", "a\x00b", "é", ":" * 256])
def test_unsupported_subject_rejected(subject: str) -> None:
    with pytest.raises(ValueError):
        Principal("provider", subject, "human")


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/keys",
        "https://issuer.test@evil.test/keys",
        "https://issuer.test/keys?redirect=evil",
        "https://issuer.test/keys#fragment",
        "file:///etc/passwd",
        "http://issuer.test/keys",
        "https://issuer.test:bad/keys",
        "https://issuer.test\\@evil.test/keys",
        "https://issuer.test/\nkeys",
    ],
)
def test_metadata_cannot_extend_trust(url: str) -> None:
    assert not trusted_endpoint(url, "https://issuer.test/tenant")


def test_endpoint_layout_and_explicit_cross_origin_trust() -> None:
    assert trusted_endpoint("https://issuer.test/keys", "https://issuer.test/tenant")
    assert trusted_endpoint("https://issuer.test:443/keys", "https://issuer.test/tenant")
    allowed = ("https://keys.test/exact",)
    assert trusted_endpoint(allowed[0], "https://issuer.test/tenant", allowed)
    assert not trusted_endpoint("https://keys.test/other", "https://issuer.test/tenant", allowed)
    assert not trusted_endpoint("http://keys.test/exact", "https://issuer.test/tenant", allowed)


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "id_token",
        "missing_kind",
        "wrong_kind",
        "missing_jti",
        "missing_client",
        "wrong_audience",
    ],
)
def test_explicit_rfc9068_profile_and_classification(failure: str | None) -> None:
    with oidc_server() as (base, keys, _state):
        settings = replace(
            base,
            oidc_token_profile="rfc9068-v1",
            principal_kind_claim="principal_type",
            principal_kind_mapping=(("person", "human"), ("robot", "service")),
        )
        payload = claims(
            settings.issuer,
            sub="external|opaque",
            principal_type="person",
            jti="unique-access-token",
            client_id="external-explorer",
        )
        payload.pop("typ")
        payload.pop("c1_principal_kind")
        header = "at+jwt"
        if failure == "id_token":
            header = "JWT"
        elif failure == "missing_kind":
            payload.pop("principal_type")
        elif failure == "wrong_kind":
            payload["principal_type"] = "provider-admin"
        elif failure == "missing_jti":
            payload.pop("jti")
        elif failure == "missing_client":
            payload.pop("client_id")
        elif failure == "wrong_audience":
            payload["aud"] = "explorer"

        async def check() -> None:
            validator = TokenValidator(settings)
            try:
                token = sign(payload, keys["rsa"], headers={"typ": header})
                if failure:
                    with pytest.raises(AuthenticationError):
                        await validator.authenticate(token)
                else:
                    principal = await validator.authenticate(token)
                    assert principal.subject == "external|opaque"
                    assert principal.kind == "human"
            finally:
                await validator.close()

        asyncio.run(check())


def test_legacy_profile_cannot_relax_kind_contract() -> None:
    with oidc_server() as (settings, _keys, _state):
        with pytest.raises(ValueError, match="cannot be overridden"):
            replace(settings, principal_kind_claim="principal_type")


@pytest.mark.parametrize(
    "failure", [None, "id", "missing_purpose", "missing_kind", "wrong_kind", "missing_jti"]
)
def test_hydra_access_only_signed_claims(failure: str | None) -> None:
    with oidc_server() as (base, keys, _state):
        settings = replace(base, oidc_token_profile="hydra-jwt-v1")
        payload = claims(settings.issuer, sub="external|user", client_id="explorer", jti="access")
        payload.pop("typ")
        payload.pop("c1_principal_kind")
        extra = {"token_use": "access", "c1_principal_kind": "human"}
        payload["ext"] = extra
        if failure == "id":
            payload["typ"] = "ID"
        elif failure == "missing_purpose":
            extra.pop("token_use")
        elif failure == "missing_kind":
            extra.pop("c1_principal_kind")
        elif failure == "wrong_kind":
            extra["c1_principal_kind"] = "administrator"
        elif failure == "missing_jti":
            payload.pop("jti")

        async def check() -> None:
            validator = TokenValidator(settings)
            try:
                token = sign(payload, keys["rsa"])
                if failure:
                    with pytest.raises(AuthenticationError):
                        await validator.authenticate(token)
                else:
                    assert (await validator.authenticate(token)).subject == "external|user"
            finally:
                await validator.close()

        asyncio.run(check())


def test_api_and_browser_audiences_must_be_distinct() -> None:
    with oidc_server() as (settings, _keys, _state):
        with pytest.raises(ValueError, match="must differ"):
            replace(settings, explorer_client_id=settings.audience)
