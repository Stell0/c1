"""M14-T03: hidden, highly relevant resources change no observation of the tested principal."""

from typing import Any


def test_t03_security_invariance_is_exact(results: dict[str, dict[str, Any]]) -> None:
    for name, result in results.items():
        security = result["security"]
        assert security["hidden_records_added"] > 0 and security["hidden_records_modified"] > 0
        assert security["observations"] == 2 * len(result["observation_digests"]), name
        assert security["score"] == 1.0, (name, security["differing"])
        assert security["passed"], name
