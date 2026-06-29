#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Extract machine-readable reviewer decisions from reviewer reports."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path

from reviewer_report_parsing import (
    parse_bool,
    parse_list,
    parse_list_in_section,
    parse_scalar,
    parse_scalar_in_section,
    section_block,
    select_machine_block,
)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def extract_block(text: str) -> str:
    """Select the last valid machine block (shared, template/noise-tolerant)."""
    return select_machine_block(text, "review_decision:")


def fallback_recommendation(text: str) -> str:
    match = re.search(r"recommendation\s*:\s*(accept|revise|reject|needs[-_ ]supervisor[-_ ]judgment)", text, re.I)
    if not match:
        return "unknown"
    value = match.group(1).lower().replace(" ", "_").replace("-", "_")
    if value == "reject":
        return "revise"
    return value


def parse_progress_review(block: str, path: Path) -> tuple[dict, list[str]]:
    errors: list[str] = []
    scoped = section_block(block, "progress_review")
    if not scoped:
        return (
            {
                "adds_executable_or_validation_value": False,
                "metadata_unlock_is_credible": False,
                "continues_metadata_streak": True,
                "blocks_acceptance": True,
                "blocking_reasons": ["missing progress_review YAML block"],
            },
            [f"{path}: missing progress_review YAML block"],
        )

    required_bool_keys = [
        "adds_executable_or_validation_value",
        "metadata_unlock_is_credible",
        "continues_metadata_streak",
        "blocks_acceptance",
    ]
    values: dict[str, object] = {}
    for key in required_bool_keys:
        raw = parse_scalar(scoped, key)
        if not raw:
            errors.append(f"{path}: missing progress_review.{key}")
            values[key] = False if key != "blocks_acceptance" else True
            continue
        values[key] = parse_bool(raw)
    blocking_reasons = parse_list(scoped, "blocking_reasons")
    values["blocking_reasons"] = blocking_reasons
    if values.get("blocks_acceptance") and not blocking_reasons:
        values["blocking_reasons"] = ["progress_review blocks acceptance"]
    if errors:
        values["blocks_acceptance"] = True
    return values, errors


def analyze_one(label: str, path: Path) -> dict:
    text = read_text(path)
    block = extract_block(text)
    errors: list[str] = []
    if block:
        recommendation = (
            parse_scalar_in_section(block, "review_decision", "recommendation")
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        blocks_acceptance_raw = parse_scalar_in_section(block, "review_decision", "blocks_acceptance")
        blocks_acceptance = parse_bool(blocks_acceptance_raw) if blocks_acceptance_raw else recommendation not in {"accept", ""}
        blocking_reasons = parse_list_in_section(block, "review_decision", "blocking_reasons")
        progress_review, progress_errors = parse_progress_review(block, path)
        errors.extend(progress_errors)
    else:
        recommendation = fallback_recommendation(text)
        blocks_acceptance = recommendation not in {"accept", "unknown"}
        blocking_reasons = []
        progress_review = {
            "adds_executable_or_validation_value": False,
            "metadata_unlock_is_credible": False,
            "continues_metadata_streak": True,
            "blocks_acceptance": True,
            "blocking_reasons": ["missing review_decision YAML block"],
        }
        errors.append(f"{path}: missing review_decision YAML block")
    if recommendation == "reject":
        recommendation = "revise"
    if recommendation not in {"accept", "revise", "needs_supervisor_judgment", "unknown"}:
        errors.append(f"{path}: unknown recommendation {recommendation!r}")
        blocks_acceptance = True
    progress_blocks = bool(progress_review.get("blocks_acceptance"))
    if progress_blocks:
        blocks_acceptance = True
    return {
        "role": label,
        "path": str(path),
        "recommendation": recommendation,
        "blocks_acceptance": bool(blocks_acceptance),
        "blocking_reasons": blocking_reasons,
        "progress_review": progress_review,
        "progress_blocks_acceptance": progress_blocks,
        "errors": errors,
    }


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer-a", required=True)
    parser.add_argument("--reviewer-b", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    reviews = [
        analyze_one("reviewer-a", Path(args.reviewer_a)),
        analyze_one("reviewer-b", Path(args.reviewer_b)),
    ]
    blocked_by = [review["role"] for review in reviews if review["blocks_acceptance"]]
    errors = [error for review in reviews for error in review["errors"]]
    result = {
        "schema_version": 1,
        "reviewers_complete": not errors,
        "blocked_by": blocked_by,
        "reviewer_a_recommendation": reviews[0]["recommendation"],
        "reviewer_b_recommendation": reviews[1]["recommendation"],
        "reviewer_a_blocks": reviews[0]["blocks_acceptance"],
        "reviewer_b_blocks": reviews[1]["blocks_acceptance"],
        "reviewer_a_progress_blocks": reviews[0]["progress_blocks_acceptance"],
        "reviewer_b_progress_blocks": reviews[1]["progress_blocks_acceptance"],
        "reviews": reviews,
        "errors": errors,
    }
    write_json_atomic(Path(args.output), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if blocked_by or errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
