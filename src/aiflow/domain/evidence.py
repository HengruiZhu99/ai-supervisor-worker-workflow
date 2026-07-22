from __future__ import annotations

import math
from typing import Any, Mapping


class EvidenceError(ValueError):
    """A Solo cycle lacks discriminating, bounded verification evidence."""


KINDS = {
    "feature",
    "bug",
    "refactor",
    "test",
    "numerical",
    "performance",
    "portability",
}


def _exit(evidence: Mapping[str, Any], key: str) -> int:
    value = evidence.get(key, {})
    if not isinstance(value, Mapping):
        raise EvidenceError(f"{key} command evidence is required")
    try:
        return int(value["exit_code"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EvidenceError(f"{key} exit code is required") from exc


def _discriminating(evidence: Mapping[str, Any], key: str, *, failing: bool) -> None:
    result = evidence.get(key, {})
    if not isinstance(result, Mapping) or not result.get("discriminating"):
        raise EvidenceError(f"{key} must be discriminating")
    code = _exit(evidence, key)
    if failing == (code == 0):
        expectation = "fail" if failing else "pass"
        raise EvidenceError(f"{key} must {expectation} for the intended reason")


def _common(evidence: Mapping[str, Any]) -> None:
    if _exit(evidence, "green") != 0 or _exit(evidence, "regression") != 0:
        raise EvidenceError("GREEN and regression commands must pass")
    review = evidence.get("cold_review", {})
    if not isinstance(review, Mapping) or review.get("status") != "pass":
        raise EvidenceError("a passing cold self-review is required")
    attempts = int(evidence.get("attempts", 0))
    questions = int(evidence.get("questions", 0))
    if attempts < 1 or attempts > 3:
        raise EvidenceError("attempt count must be between one and three")
    if questions < 0 or questions > 2:
        raise EvidenceError("question count must be between zero and two")


def _numerical(evidence: Mapping[str, Any]) -> None:
    for key in ("reference", "oracle_provenance", "units", "dimensions", "shapes"):
        if evidence.get(key) in (None, "", [], {}):
            raise EvidenceError(f"numerical evidence requires {key}")
    if (
        not isinstance(evidence.get("dimensions"), int)
        or int(evidence["dimensions"]) < 1
    ):
        raise EvidenceError("numerical dimensions must be a positive integer")
    _numerical_shapes(evidence.get("shapes"))
    _numerical_tolerance(evidence.get("tolerance", {}))
    _numerical_convergence(evidence.get("convergence", {}))
    if not isinstance(evidence.get("deterministic_seed"), int):
        raise EvidenceError("numerical evidence requires a deterministic seed")


def _numerical_shapes(shapes: Any) -> None:
    if (
        not isinstance(shapes, list)
        or not shapes
        or any(
            not isinstance(shape, list)
            or not shape
            or any(not isinstance(size, int) or size < 1 for size in shape)
            for shape in shapes
        )
    ):
        raise EvidenceError("numerical shapes must contain positive integer extents")


def _numerical_tolerance(tolerance: Any) -> None:
    if (
        not isinstance(tolerance, Mapping)
        or not {"absolute", "relative", "justification"} <= tolerance.keys()
    ):
        raise EvidenceError("numerical tolerance requires bounds and justification")
    bounds = (float(tolerance["absolute"]), float(tolerance["relative"]))
    if any(not math.isfinite(value) or value < 0 for value in bounds):
        raise EvidenceError("numerical tolerances must be finite and nonnegative")


def _numerical_convergence(convergence: Any) -> None:
    if not isinstance(convergence, Mapping) or int(convergence.get("levels", 0)) < 3:
        raise EvidenceError("numerical convergence evidence is required")
    observed = float(convergence.get("observed_order", float("nan")))
    minimum = float(convergence.get("minimum_order", float("nan")))
    if (
        not all(math.isfinite(value) for value in (observed, minimum))
        or observed < minimum
    ):
        raise EvidenceError("observed convergence order is below the contract")


def _performance(evidence: Mapping[str, Any]) -> None:
    baseline = float(evidence.get("baseline_metric", 0))
    candidate = float(evidence.get("candidate_metric", 0))
    allowance = float(evidence.get("max_regression", -1))
    if not all(math.isfinite(value) for value in (baseline, candidate, allowance)):
        raise EvidenceError("performance metrics must be finite")
    if baseline <= 0 or candidate <= 0 or not 0 <= allowance < 1:
        raise EvidenceError(
            "performance baseline, candidate, and regression bound are invalid"
        )
    _performance_protocol(evidence)
    direction = str(evidence["direction"])
    if _performance_regressed(direction, baseline, candidate, allowance):
        raise EvidenceError("performance regression exceeds the declared guard")


def _performance_protocol(evidence: Mapping[str, Any]) -> None:
    required = (
        bool(evidence.get("metric")),
        evidence.get("direction") in {"lower-is-better", "higher-is-better"},
        int(evidence.get("samples", 0)) >= 3,
        int(evidence.get("warmups", 0)) >= 1,
        bool(evidence.get("comparability")),
        evidence.get("equivalent_work") is True,
        evidence.get("output_equivalent") is True,
    )
    if not all(required):
        raise EvidenceError(
            "performance evidence requires a metric and at least three samples"
        )


def _performance_regressed(
    direction: str, baseline: float, candidate: float, allowance: float
) -> bool:
    return (
        candidate > baseline * (1 + allowance)
        if direction == "lower-is-better"
        else candidate < baseline * (1 - allowance)
    )


def _portability(evidence: Mapping[str, Any]) -> None:
    backends = evidence.get("backends", {})
    if not isinstance(backends, Mapping) or len(backends) < 2:
        raise EvidenceError("portability evidence requires at least two backends")
    required = {"status", "dtype", "layout", "provenance"}
    for name, result in backends.items():
        if not isinstance(result, Mapping) or not required <= result.keys():
            raise EvidenceError(
                f"portability backend {name} lacks structured provenance"
            )
        if result.get("status") != "pass":
            raise EvidenceError("every declared portability backend must pass")


def _kind_baseline(kind: str, evidence: Mapping[str, Any]) -> None:
    if kind == "feature":
        _discriminating(evidence, "red", failing=True)
        if not evidence.get("observable"):
            raise EvidenceError("feature evidence requires a new observable")
    elif kind == "bug":
        _discriminating(evidence, "red", failing=True)
        if not evidence.get("reproduction"):
            raise EvidenceError("bug evidence requires a pre-fix reproduction")
    elif kind == "refactor":
        _discriminating(evidence, "characterization", failing=False)
        if evidence.get("behavior_equivalent") is not True:
            raise EvidenceError(
                "refactor evidence requires characterization and equivalence"
            )
    elif kind == "test":
        _discriminating(evidence, "negative_control", failing=True)
        if not evidence.get("oracle"):
            raise EvidenceError("test-only evidence requires an independent oracle")


def validate_cycle(kind: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
    if kind not in KINDS:
        raise EvidenceError(f"unsupported Solo task kind: {kind}")
    _common(evidence)
    _kind_baseline(kind, evidence)
    if kind == "numerical":
        _numerical(evidence)
    elif kind == "performance":
        _performance(evidence)
    elif kind == "portability":
        _portability(evidence)
    return {"kind": kind, "status": "VERIFIED", "attempts": int(evidence["attempts"])}
