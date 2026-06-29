#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Check reviewer-reported diff coverage against changed files."""

from __future__ import annotations

import argparse
from pathlib import Path

from reviewer_report_parsing import (
    parse_bool,
    parse_list,
    parse_scalar,
    section_block,
    select_machine_block,
)


def changed_files(path: Path) -> set[str]:
    files: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if not parts:
            continue
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            files.add(parts[2])
        elif len(parts) >= 2:
            files.add(parts[1])
    return files


def extract_coverage_block(text: str) -> str:
    """Return the precise ``diff_coverage`` section of the last valid machine block.

    Uses the shared block selector so an earlier echoed prompt template or a
    tokenized transcript fragment cannot fail an otherwise-complete review.
    """
    block = select_machine_block(text, "diff_coverage:")
    if not block:
        return ""
    scoped = section_block(block, "diff_coverage")
    return scoped if scoped else block


def parse_report(path: Path) -> tuple[bool, set[str], list[str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    block = extract_coverage_block(text)
    errors: list[str] = []
    if not block:
        return False, set(), [f"{path}: missing diff_coverage block"]
    full_raw = parse_scalar(block, "full_diff_reviewed")
    full = parse_bool(full_raw) if full_raw else False
    if not full:
        errors.append(f"{path}: full_diff_reviewed is not true")
    reviewed = set(parse_list(block, "files_reviewed"))
    unreviewed = parse_list(block, "unreviewed_files")
    if unreviewed:
        errors.append(f"{path}: unreviewed_files is not empty: {', '.join(unreviewed)}")
    return full, reviewed, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("changed_files")
    parser.add_argument("reviewer_reports", nargs="+")
    args = parser.parse_args()

    expected = changed_files(Path(args.changed_files))
    errors: list[str] = []
    for report in args.reviewer_reports:
        path = Path(report)
        if not path.exists():
            errors.append(f"{path}: report does not exist")
            continue
        _, reviewed, report_errors = parse_report(path)
        errors.extend(report_errors)
        missing = expected - reviewed
        extra = reviewed - expected
        if missing:
            errors.append(f"{path}: missing reviewed files: {', '.join(sorted(missing))}")
        if extra:
            errors.append(f"{path}: files_reviewed has unknown paths: {', '.join(sorted(extra))}")

    if errors:
        print("Reviewer coverage check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Reviewer coverage check passed for {len(expected)} changed file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
