#!/usr/bin/env python3
"""Print a compact summary of collected AI agent metrics."""

from __future__ import annotations

import json
from pathlib import Path


def fmt_int(value: object) -> str:
    return "" if value is None else f"{int(value):,}"


def fmt_seconds(value: object) -> str:
    if value is None:
        return ""
    return f"{float(value) / 1000.0:.1f}s"


def main() -> int:
    path = Path(".ai/metrics/runs.jsonl")
    if not path.exists():
        print("No metrics found")
        return 0

    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not rows:
        print("No metrics found")
        return 0

    print(
        f"{'role':<10} {'job/run':<18} {'attempt':<7} {'model':<28} "
        f"{'wall':>9} {'api':>9} {'input':>12} {'output':>12} {'cache read':>12} {'exit':>5}"
    )
    print("-" * 130)
    for row in rows[-80:]:
        role = row.get("role", "")
        if row.get("reviewer_role"):
            role = str(row["reviewer_role"])
        job = row.get("job_id") or row.get("run_id") or ""
        model = str(row.get("model") or row.get("configured_model") or "")[:28]
        print(
            f"{role:<10} {str(job):<18} {str(row.get('attempt') or ''):<7} {model:<28} "
            f"{fmt_seconds(row.get('wall_ms')):>9} {fmt_seconds(row.get('api_ms')):>9} "
            f"{fmt_int(row.get('input_tokens')):>12} {fmt_int(row.get('output_tokens')):>12} "
            f"{fmt_int(row.get('cache_read_tokens')):>12} {str(row.get('exit_code', '')):>5}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
