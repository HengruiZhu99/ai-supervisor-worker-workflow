from __future__ import annotations

from typing import Any, Mapping


class EvidenceError(ValueError):
    """A Solo cycle lacks discriminating, bounded verification evidence."""


KINDS = {"feature", "bug", "refactor", "numerical", "performance", "portability"}


def _exit(evidence: Mapping[str, Any], key: str) -> int:
    value = evidence.get(key, {})
    if not isinstance(value, Mapping):
        raise EvidenceError(f"{key} command evidence is required")
    try:
        return int(value["exit_code"])
    except (KeyError, TypeError, ValueError) as exc:
        raise EvidenceError(f"{key} exit code is required") from exc


def _common(evidence: Mapping[str, Any]) -> None:
    if _exit(evidence, "red") == 0 or not evidence.get("red", {}).get("discriminating"):
        raise EvidenceError("RED must fail for the intended observable reason")
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
    for key in ("reference", "units", "dimensions", "shapes"):
        if evidence.get(key) in (None, "", [], {}):
            raise EvidenceError(f"numerical evidence requires {key}")
    tolerance = evidence.get("tolerance", {})
    if not isinstance(tolerance, Mapping) or not {"absolute", "relative"} <= tolerance.keys():
        raise EvidenceError("numerical tolerance requires absolute and relative values")
    convergence = evidence.get("convergence", {})
    if not isinstance(convergence, Mapping):
        raise EvidenceError("numerical convergence evidence is required")
    if float(convergence.get("observed_order", 0)) < float(convergence.get("minimum_order", 1)):
        raise EvidenceError("observed convergence order is below the contract")


def _performance(evidence: Mapping[str, Any]) -> None:
    baseline = float(evidence.get("baseline_metric", 0))
    candidate = float(evidence.get("candidate_metric", 0))
    allowance = float(evidence.get("max_regression", -1))
    if baseline <= 0 or candidate <= 0 or not 0 <= allowance < 1:
        raise EvidenceError("performance baseline, candidate, and regression bound are invalid")
    if not evidence.get("metric") or int(evidence.get("samples", 0)) < 3:
        raise EvidenceError("performance evidence requires a metric and at least three samples")
    if candidate > baseline * (1 + allowance):
        raise EvidenceError("performance regression exceeds the declared guard")


def _portability(evidence: Mapping[str, Any]) -> None:
    backends = evidence.get("backends", {})
    if not isinstance(backends, Mapping) or len(backends) < 2:
        raise EvidenceError("portability evidence requires at least two backends")
    if any(status != "pass" for status in backends.values()):
        raise EvidenceError("every declared portability backend must pass")


def validate_cycle(kind: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
    if kind not in KINDS:
        raise EvidenceError(f"unsupported Solo task kind: {kind}")
    _common(evidence)
    if kind == "feature" and not evidence.get("observable"):
        raise EvidenceError("feature evidence requires a new observable")
    if kind == "bug" and not evidence.get("reproduction"):
        raise EvidenceError("bug evidence requires a pre-fix reproduction")
    if kind == "refactor" and (
        not evidence.get("characterization") or evidence.get("behavior_equivalent") is not True
    ):
        raise EvidenceError("refactor evidence requires characterization and equivalence")
    if kind == "numerical":
        _numerical(evidence)
    elif kind == "performance":
        _performance(evidence)
    elif kind == "portability":
        _portability(evidence)
    return {"kind": kind, "status": "VERIFIED", "attempts": int(evidence["attempts"])}
