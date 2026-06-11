#!/usr/bin/env python3
"""List project-local and reusable workflow skills for duplication checks."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def git_root() -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    if result.returncode != 0:
        raise SystemExit("list_skills.py must run inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def metadata(skill_file: Path) -> dict[str, str]:
    try:
        text = skill_file.read_text(encoding="utf-8")
    except OSError:
        return {}
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    data: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def iter_skill_files(root: Path, base: Path) -> list[Path]:
    skill_root = root / base
    if not skill_root.exists():
        return []
    return sorted(skill_root.glob("*/SKILL.md"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--include-system",
        action="store_true",
        help="include the user's ~/.cursor and ~/.codex skills when available",
    )
    args = parser.parse_args()

    root = git_root()
    locations: list[tuple[str, Path, Path]] = [
        ("project", root, Path("skills")),
        ("workflow-submodule", root, Path("external/ai-supervisor-worker-workflow/skills")),
        ("workflow-installed", root, Path("skills")),
    ]
    if args.include_system:
        locations.append(("cursor-user", Path.home() / ".cursor", Path("skills")))
        locations.append(("codex-user", Path.home() / ".codex", Path("skills")))

    seen: set[Path] = set()
    rows = []
    for label, location_root, relative in locations:
        for skill_file in iter_skill_files(location_root, relative):
            resolved = skill_file.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            meta = metadata(skill_file)
            try:
                display_path = skill_file.relative_to(root)
            except ValueError:
                display_path = skill_file
            rows.append(
                {
                    "location": label,
                    "name": meta.get("name") or skill_file.parent.name,
                    "description": meta.get("description", ""),
                    "path": str(display_path),
                }
            )

    if not rows:
        print("No skills found.")
        return 0

    widths = {
        "location": max(len("location"), *(len(row["location"]) for row in rows)),
        "name": max(len("name"), *(len(row["name"]) for row in rows)),
        "path": max(len("path"), *(len(row["path"]) for row in rows)),
    }
    print(f"{'location':<{widths['location']}}  {'name':<{widths['name']}}  {'path':<{widths['path']}}  description")
    print(f"{'-' * widths['location']}  {'-' * widths['name']}  {'-' * widths['path']}  {'-' * 11}")
    for row in rows:
        print(
            f"{row['location']:<{widths['location']}}  "
            f"{row['name']:<{widths['name']}}  "
            f"{row['path']:<{widths['path']}}  "
            f"{row['description']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
