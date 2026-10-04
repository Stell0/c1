"""M14-T01: every generated record, conflict, document and export page survives exactly."""

from typing import Any


def test_t01_storage_fidelity_is_exact(results: dict[str, dict[str, Any]]) -> None:
    for name, result in results.items():
        fidelity = result["fidelity"]
        assert fidelity["records"] == result["corpus"]["records"], name
        assert fidelity["score"] == 1.0 and not fidelity["losses"], (name, fidelity["losses"])
        assert fidelity["conflicts_checked"] > 0, name
        assert fidelity["conflicts_preserved"] == fidelity["conflicts_checked"], name
        assert fidelity["documents_exact"] == fidelity["documents_checked"] > 0, name
        roundtrip = fidelity["export_roundtrip"]
        assert roundtrip["identities_identical"], name
        assert roundtrip["corpus_records_exported"] == result["corpus"]["records"], name
        assert fidelity["passed"], name
