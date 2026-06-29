#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Extract a structured worker handoff from raw agent output.

The raw worker transcript is audit evidence.  It can contain prompt echoes,
intermediate reasoning, stale copied feedback, and token-stream fragments.  This
helper extracts only the final structured handoff sections that downstream
reports and commit docs should use as worker narrative.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


SECTION_ALIASES = {
    "summary": ("summary",),
    "files_changed": ("files changed", "changed files"),
    "commits_made": ("commits made", "commits"),
    "tests_run": ("tests run and results", "tests run", "validation"),
    "scientific_assumptions": ("scientific assumptions", "assumptions"),
    "known_limitations": ("known limitations", "limitations"),
    "suggested_follow_up": ("suggested follow-up", "suggested follow up", "follow-up", "follow up"),
    "workflow_friction": ("workflow friction",),
    "skill_suggestions": ("skill suggestions",),
}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def clean_line(line: str) -> str:
    return line.rstrip()


def final_structured_region(text: str) -> tuple[str, str]:
    """Return the most likely final report region and extraction quality."""

    lines = text.splitlines()
    summary_indices = [
        index for index, line in enumerate(lines)
        if re.match(r"^\s*#{1,3}\s+summary\s*$", line, flags=re.I)
    ]
    if summary_indices:
        return "\n".join(lines[summary_indices[-1]:]).strip(), "structured_sections"

    result_indices = [
        index for index, line in enumerate(lines)
        if line.strip().lower() in {"[result]", "result:"}
    ]
    if result_indices and result_indices[-1] + 1 < len(lines):
        return "\n".join(lines[result_indices[-1] + 1:]).strip(), "result_suffix"

    return "", "missing_or_unstructured"


def parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = ""
    for raw_line in text.splitlines():
        line = clean_line(raw_line)
        stripped = line.strip()
        if current and re.match(r"^\[[a-z_ -]+\]$", stripped, flags=re.I):
            break
        match = re.match(r"^\s*#{1,3}\s+(.+?)\s*$", line)
        if match:
            current = match.group(1).strip().lower()
            sections.setdefault(current, [])
            continue
        if current:
            sections.setdefault(current, []).append(line)

    parsed: dict[str, str] = {}
    for field, aliases in SECTION_ALIASES.items():
        for heading, body in sections.items():
            if any(alias == heading or alias in heading for alias in aliases):
                parsed[field] = "\n".join(body).strip()
                break
        parsed.setdefault(field, "")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--raw-output", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    raw_path = Path(args.raw_output)
    raw_text = read_text(raw_path)
    region, quality = final_structured_region(raw_text)
    parsed = parse_sections(region) if region else {field: "" for field in SECTION_ALIASES}

    if not parsed.get("summary"):
        parsed["summary"] = (
            "No clean structured worker handoff was found in the raw transcript. "
            "Review the raw transcript only as audit evidence."
        )

    data = {
        "schema_version": 1,
        "job_id": args.job_id,
        "attempt": args.attempt,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source_raw_output": str(raw_path),
        "handoff_quality": quality,
        **parsed,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
