#!/usr/bin/env python3
"""Check reviewer-reported diff coverage against changed files."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


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
    fenced_blocks = re.findall(r"```(?:yaml|yml)\s*\n(.*?diff_coverage:.*?)```", text, re.S | re.I)
    if fenced_blocks:
        return fenced_blocks[-1]
    marker = text.rfind("diff_coverage:")
    return text[marker:] if marker >= 0 else ""


def parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"true", "yes"}


def parse_list(block: str, key: str) -> list[str]:
    lines = block.splitlines()
    values: list[str] = []
    in_list = False
    base_indent = 0
    for line in lines:
        if re.match(rf"^\s*{re.escape(key)}\s*:\s*\[\s*\]\s*$", line):
            return []
        match = re.match(rf"^(\s*){re.escape(key)}\s*:\s*$", line)
        if match:
            in_list = True
            base_indent = len(match.group(1))
            continue
        if in_list:
            if line.strip().startswith("- "):
                values.append(line.strip()[2:].strip().strip("'\""))
                continue
            if line.strip() and len(line) - len(line.lstrip()) <= base_indent:
                break
    return values


def parse_report(path: Path) -> tuple[bool, set[str], list[str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    block = extract_coverage_block(text)
    errors: list[str] = []
    if not block:
        return False, set(), [f"{path}: missing diff_coverage block"]
    full_match = re.search(r"^\s*full_diff_reviewed\s*:\s*(\S+)", block, re.M)
    full = parse_bool(full_match.group(1)) if full_match else False
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
