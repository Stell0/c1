"""M14-T05: every D9 measurement is present per scale, with the host record."""

from typing import Any


def test_t05_performance_envelope_is_measured(results: dict[str, dict[str, Any]]) -> None:
    for name, result in results.items():
        load = result["load"]
        assert load["seconds"] > 0 and load["records"] == result["corpus"]["records"], name
        assert load["storage_bytes_before"] and load["storage_bytes_after"], name
        assert load["storage_bytes_after"] > load["storage_bytes_before"], name
        performance = result["performance"]
        assert performance["repeats"] == 5
        assert set(performance["families"]) == set(result["quality"]["families"]), name
        for family, row in performance["families"].items():
            assert row["samples"] >= 5 and row["median_ms"] > 0 and row["p90_ms"] > 0, family
            assert row["openfga_requests_per_query"] >= 0, family
        assert set(performance["context_by_budget"]) == {"8192", "32768", "65536"}, name
        assert performance["c1_memory_peak_bytes"], name
        assert performance["storage_bytes"], name
        for key in ("hostname", "kernel", "cpu", "memory", "podman"):
            assert result["host"][key], (name, key)
