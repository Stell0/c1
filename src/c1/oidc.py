"""Endpoint trust policy shared by bearer validation and browser OIDC.

Metadata cannot extend trust: cross-origin endpoints must be exact URLs in
operator-owned configuration. Redirects remain disabled in HTTP clients.
"""

from __future__ import annotations

from urllib.parse import urlsplit


def trusted_endpoint(url: object, issuer: str, allowed: tuple[str, ...] = ()) -> bool:
    if not isinstance(url, str) or not url or any(ord(c) < 33 for c in url) or "\\" in url:
        return False
    try:
        endpoint, origin = urlsplit(url), urlsplit(issuer)
        if (
            endpoint.scheme not in {"https", "http"}
            or not endpoint.hostname
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.fragment
            or endpoint.query
        ):
            return False
        same = (
            endpoint.scheme,
            endpoint.hostname,
            endpoint.port or (443 if endpoint.scheme == "https" else 80),
        ) == (
            origin.scheme,
            origin.hostname,
            origin.port or (443 if origin.scheme == "https" else 80),
        )
        # Cross-origin plain HTTP is never authorized by an allowlist.
        return same or (endpoint.scheme == "https" and url in allowed)
    except ValueError:
        return False
