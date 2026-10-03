"""Browser-facing request safety: headers, CSRF origin checks, form parsing (M12 D4, D5)."""

from __future__ import annotations

from urllib.parse import parse_qsl

from starlette.datastructures import Headers

MAX_FORM_BYTES = 64 * 1024
MAX_FORM_FIELDS = 400

CSP = (
    "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; "
    "frame-ancestors 'none'; base-uri 'none'"
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    # same-origin: no referrer leaves the Explorer, and same-origin form posts
    # carry their real Origin (no-referrer makes browsers send "Origin: null").
    "Referrer-Policy": "same-origin",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class FormError(ValueError):
    """A rejected browser form; the message is safe to log."""


def same_origin(headers: Headers, origin: str) -> bool:
    """A state change must come from the Explorer's own origin (D4)."""
    supplied = headers.get("origin")
    if supplied is not None:
        return supplied == origin
    # Browsers send Origin on POST; a missing one is refused rather than guessed.
    return False


def parse_form(body: bytes, content_type: str | None) -> dict[str, list[str]]:
    """Strict url-encoded form parsing with size, field and encoding limits."""
    media = (content_type or "").split(";", 1)[0].strip().lower()
    if media != "application/x-www-form-urlencoded":
        raise FormError("unsupported_form_encoding")
    if len(body) > MAX_FORM_BYTES:
        raise FormError("form_too_large")
    try:
        text = body.decode("ascii")
        pairs = parse_qsl(
            text,
            keep_blank_values=True,
            strict_parsing=bool(text),
            encoding="utf-8",
            errors="strict",
            max_num_fields=MAX_FORM_FIELDS,
        )
    except (UnicodeError, ValueError):
        raise FormError("malformed_form") from None
    result: dict[str, list[str]] = {}
    for key, value in pairs:
        if any(ord(ch) < 32 and ch not in "\t\r\n" for ch in value) or "\x7f" in value:
            raise FormError("control_character")
        result.setdefault(key, []).append(value)
    return result


def single(form: dict[str, list[str]], name: str, *, required: bool = True) -> str:
    """One value per field; duplicates are refused (D4)."""
    values = form.get(name, [])
    if len(values) > 1:
        raise FormError("duplicate_field")
    if not values:
        if required:
            raise FormError("missing_field")
        return ""
    return values[0]
