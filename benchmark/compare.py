"""Baseline subset and per-family comparison (M14 D11). There is no aggregate score."""

from __future__ import annotations

from typing import Any

SLOWDOWN = 1.5


def scale_subset(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "corpus": {
            k: result["corpus"][k]
            for k in ("corpus", "seed", "scale", "records", "records_sha256", "gold_sha256")
        },
        "c1_revision": result["c1_revision"],
        "host": {k: result["host"].get(k) for k in ("hostname", "cpu", "memory", "podman")},
        "fidelity": {"score": result["fidelity"]["score"], "passed": result["fidelity"]["passed"]},
        "quality": result["quality"]["families"],
        "security": {"score": result["security"]["score"], "passed": result["security"]["passed"]},
        "revocation": {"passed": result["revocation"]["passed"]},
        "performance": {k: v["median_ms"] for k, v in result["performance"]["families"].items()},
    }


def baseline_subset(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "format": "c1-benchmark-baseline/1",
        "scales": {name: scale_subset(r) for name, r in sorted(results.items())},
    }


def compare(baseline: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Classify one results file against the baseline scale with the same corpus scale."""
    current = scale_subset(result)
    scale = next(
        (
            name
            for name, entry in baseline["scales"].items()
            if entry["corpus"]["scale"] == current["corpus"]["scale"]
        ),
        None,
    )
    report: dict[str, Any] = {
        "scale": scale,
        "hard_failures": [],
        "changes": [],
        "performance_warnings": [],
        "notes": [],
    }
    if current["fidelity"]["score"] < 1.0 or not current["fidelity"]["passed"]:
        report["hard_failures"].append("fidelity")
    if current["security"]["score"] < 1.0 or not current["security"]["passed"]:
        report["hard_failures"].append("security")
    if not current["revocation"]["passed"]:
        report["hard_failures"].append("revocation")
    if scale is None:
        report["notes"].append("no baseline for this corpus scale")
        return report
    reference = baseline["scales"][scale]
    for key in ("records_sha256", "gold_sha256"):
        if reference["corpus"][key] != current["corpus"][key]:
            report["notes"].append(f"corpus {key} differs: quality is not comparable")
    for family in sorted(set(reference["quality"]) | set(current["quality"])):
        old, new = reference["quality"].get(family, {}), current["quality"].get(family, {})
        for metric in sorted(set(old) | set(new)):
            if old.get(metric) != new.get(metric):
                before, after = old.get(metric), new.get(metric)
                direction = "changed"
                if isinstance(before, float) and isinstance(after, float):
                    direction = "higher" if after > before else "lower"
                report["changes"].append(
                    {
                        "family": family,
                        "metric": metric,
                        "baseline": before,
                        "current": after,
                        "direction": direction,
                    }
                )
    same_host = reference["host"].get("hostname") == current["host"].get("hostname")
    if not same_host:
        report["notes"].append("different host: performance not compared")
    else:
        for family, median in sorted(current["performance"].items()):
            before = reference["performance"].get(family)
            if before and median > SLOWDOWN * before:
                report["performance_warnings"].append(
                    {"family": family, "baseline_median_ms": before, "current_median_ms": median}
                )
    return report
