"""M14-T06: the deterministic baseline runs; optional configurations are NOT_AVAILABLE."""

from typing import Any

from benchmark.configurations import CONFIGURATIONS


def test_t06_ablation_registry_reports_honestly(results: dict[str, dict[str, Any]]) -> None:
    for name, result in results.items():
        configurations = result["configurations"]
        assert set(configurations) == set(CONFIGURATIONS), name
        assert configurations["deterministic"] == {"status": "RUN"}, name
        for key, value in configurations.items():
            if key != "deterministic":
                assert value["status"] == "NOT_AVAILABLE" and value["reason"], (name, key)
        # The baseline ran with no optional component and no AI provider settings.
        assert result["quality"]["families"], name
