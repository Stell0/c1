"""M14-T04: after revocation no team resource appears at head or at the old revision."""

from typing import Any


def test_t04_revocation_has_no_leak_and_regrant_restores(
    results: dict[str, dict[str, Any]],
) -> None:
    for name, result in results.items():
        revocation = result["revocation"]
        assert revocation["team_resources"] > 0, name
        expected = len(result["observation_digests"])
        assert revocation["observations"] == {
            "head": expected,
            "pre_revocation_revision": expected,
        }, name
        assert not revocation["leaks"], (name, revocation["leaks"])
        assert revocation["restored_identical"], (name, revocation["restored_differing"])
        assert revocation["passed"], name
