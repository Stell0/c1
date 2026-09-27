import pytest

from c1.query.cursor import CursorCodec, CursorError


def test_cursor_binds_principal_revision_filter_order_and_expiry() -> None:
    codec = CursorCodec("s" * 32)
    token = codec.encode(
        principal="user:issuer.alice",
        revision="commit-1",
        filter_digest="digest",
        order="label",
        last_key=("ada", "urn:test:ada"),
        now=100,
    )
    expected = dict(
        principal="user:issuer.alice", revision="commit-1", filter_digest="digest", order="label"
    )
    position = codec.decode(token, now=101, **expected)
    assert position.last_key == ("ada", "urn:test:ada")
    assert position.exp == 1000
    implicit = {key: value for key, value in expected.items() if key != "revision"}
    assert codec.decode(token, now=101, **implicit).revision == "commit-1"
    for field, changed in (
        ("principal", "user:issuer.bob"),
        ("revision", "commit-2"),
        ("filter_digest", "other"),
        ("order", "id"),
    ):
        with pytest.raises(CursorError):
            codec.decode(token, now=101, **{**expected, field: changed})
    with pytest.raises(CursorError):
        codec.decode(token, now=1000, **expected)


def test_cursor_tamper_and_malformed_rejected() -> None:
    codec = CursorCodec("s" * 32)
    expected = dict(
        principal="user:issuer.alice", revision="commit-1", filter_digest="digest", order="id"
    )
    token = codec.encode(last_key=("urn:test:x", "urn:test:x"), now=100, **expected)
    with pytest.raises(CursorError):
        codec.decode(token[:-1] + ("A" if token[-1] != "A" else "B"), now=101, **expected)
    for bad in ("", "!", "x" * 9000):
        with pytest.raises(CursorError):
            codec.decode(bad, now=101, **expected)
    with pytest.raises(ValueError):
        CursorCodec("short")
