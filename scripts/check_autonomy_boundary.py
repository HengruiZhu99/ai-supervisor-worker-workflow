#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Check whether a milestone transition requires a human review gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_CONFIG = Path(".ai/supervisor/autonomy_delegation.json")


def normalize_milestone(value: str) -> str:
    value = value.strip().upper()
    if value.startswith("M"):
        return value
    return f"M{value}"


def load_config(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"autonomy delegation file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid autonomy delegation JSON in {path}: {exc}") from exc


def check_transition(
    config: dict[str, object],
    current: str,
    next_milestone: str,
    exceptions: list[str],
) -> dict[str, object]:
    current = normalize_milestone(current)
    next_milestone = normalize_milestone(next_milestone)
    active = bool(config.get("active", False))
    tranche = config.get("current_tranche", {})
    if not isinstance(tranche, dict):
        tranche = {}

    delegated = {
        normalize_milestone(str(item))
        for item in tranche.get("delegated_milestones", [])
        if str(item).strip()
    }
    review_before = {
        normalize_milestone(str(item))
        for item in tranche.get("review_required_before", [])
        if str(item).strip()
    }
    for boundary in config.get("future_human_boundaries", []):
        if isinstance(boundary, dict) and str(boundary.get("before_milestone", "")).strip():
            review_before.add(normalize_milestone(str(boundary["before_milestone"])))

    reasons: list[str] = []
    if not active:
        reasons.append("autonomy delegation is inactive")
    if exceptions:
        reasons.extend(f"exception trigger: {item}" for item in exceptions)
    if next_milestone in review_before:
        reasons.append(f"preset human boundary before {next_milestone}")
    if next_milestone not in delegated and next_milestone not in review_before:
        reasons.append(f"{next_milestone} is not delegated by the active tranche")

    human_review_required = bool(reasons)
    return {
        "current": current,
        "next": next_milestone,
        "active": active,
        "tranche_id": tranche.get("id", ""),
        "delegated_milestones": sorted(delegated),
        "preset_review_before": sorted(review_before),
        "human_review_required": human_review_required,
        "reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--current", required=True)
    parser.add_argument("--next", required=True, dest="next_milestone")
    parser.add_argument(
        "--exception",
        action="append",
        default=[],
        help="Exception-trigger reason. May be passed multiple times.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    payload = check_transition(
        load_config(Path(args.config)),
        args.current,
        args.next_milestone,
        args.exception,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        verdict = "human review required" if payload["human_review_required"] else "delegated"
        print(f"{payload['current']} -> {payload['next']}: {verdict}")
        for reason in payload["reasons"]:
            print(f"- {reason}")
    return 0 if not payload["human_review_required"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
