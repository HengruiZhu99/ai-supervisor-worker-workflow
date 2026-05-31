#!/usr/bin/env python3
"""Extract machine-readable reviewer decisions from reviewer reports."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def extract_block(text: str) -> str:
    blocks = re.findall(r"```(?:yaml|yml)\s*\n(.*?review_decision:.*?)```", text, re.S | re.I)
    if blocks:
        return blocks[-1]
    marker = text.rfind("review_decision:")
    return text[marker:] if marker >= 0 else ""


def parse_bool(raw: str) -> bool:
    return raw.strip().lower().strip("'\"") in {"true", "yes", "1"}


def parse_scalar(block: str, key: str) -> str:
    match = re.search(rf"^\s*{re.escape(key)}\s*:\s*(.*?)\s*$", block, re.M)
    return match.group(1).strip().strip("'\"") if match else ""


def parse_list(block: str, key: str) -> list[str]:
    if re.search(rf"^\s*{re.escape(key)}\s*:\s*\[\s*\]\s*$", block, re.M):
        return []
    lines = block.splitlines()
    values: list[str] = []
    in_list = False
    base_indent = 0
    for line in lines:
        match = re.match(rf"^(\s*){re.escape(key)}\s*:\s*$", line)
        if match:
            in_list = True
            base_indent = len(match.group(1))
            continue
        if in_list:
            stripped = line.strip()
            if stripped.startswith("- "):
                values.append(stripped[2:].strip().strip("'\""))
                continue
            if stripped and len(line) - len(line.lstrip()) <= base_indent:
                break
    return values


def fallback_recommendation(text: str) -> str:
    match = re.search(r"recommendation\s*:\s*(accept|revise|reject|needs[-_ ]supervisor[-_ ]judgment)", text, re.I)
    if not match:
        return "unknown"
    value = match.group(1).lower().replace(" ", "_").replace("-", "_")
    if value == "reject":
        return "revise"
    return value


def analyze_one(label: str, path: Path) -> dict:
    text = read_text(path)
    block = extract_block(text)
    errors: list[str] = []
    if block:
        recommendation = parse_scalar(block, "recommendation").lower().replace("-", "_").replace(" ", "_")
        blocks_acceptance_raw = parse_scalar(block, "blocks_acceptance")
        blocks_acceptance = parse_bool(blocks_acceptance_raw) if blocks_acceptance_raw else recommendation not in {"accept", ""}
        blocking_reasons = parse_list(block, "blocking_reasons")
    else:
        recommendation = fallback_recommendation(text)
        blocks_acceptance = recommendation not in {"accept", "unknown"}
        blocking_reasons = []
        errors.append(f"{path}: missing review_decision YAML block")
    if recommendation == "reject":
        recommendation = "revise"
    if recommendation not in {"accept", "revise", "needs_supervisor_judgment", "unknown"}:
        errors.append(f"{path}: unknown recommendation {recommendation!r}")
        blocks_acceptance = True
    return {
        "role": label,
        "path": str(path),
        "recommendation": recommendation,
        "blocks_acceptance": bool(blocks_acceptance),
        "blocking_reasons": blocking_reasons,
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
        "reviews": reviews,
        "errors": errors,
    }
    write_json_atomic(Path(args.output), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if blocked_by or errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
