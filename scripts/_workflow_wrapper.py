#!/usr/bin/env python3
from __future__ import annotations

import os
import runpy
import subprocess
import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main_worktree(root: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    common_dir = Path(result.stdout.strip())
    if common_dir.name == ".git":
        return common_dir.parent
    return None


def candidate_roots(root: Path) -> list[Path]:
    candidates: list[Path] = []
    env_root = os.environ.get("AI_WORKFLOW_PACKAGE_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    candidates.append(root / "external" / "ai-supervisor-worker-workflow")
    main_root = main_worktree(root)
    if main_root and main_root != root:
        candidates.append(main_root / "external" / "ai-supervisor-worker-workflow")
    return candidates


def main(script_name: str | None = None) -> int:
    root = project_root()
    script_name = script_name or Path(sys.argv[0]).name
    checked = []
    for package_root in candidate_roots(root):
        target = package_root / "scripts" / script_name
        checked.append(str(target))
        if target.exists():
            sys.argv[0] = str(target)
            runpy.run_path(str(target), run_name="__main__")
            return 0
    raise SystemExit("workflow package script not found; checked:\n- " + "\n- ".join(checked))


if __name__ == "__main__":
    raise SystemExit(main())
