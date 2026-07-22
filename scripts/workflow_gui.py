#!/usr/bin/env python3
"""Deprecated launcher for the project-isolated AIFLOW GUI."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.cli.main import main  # noqa: E402


if __name__ == "__main__":
    print(
        "warning: scripts/workflow_gui.py is deprecated; use `aiflow gui` "
        "(Codex gpt-5.6-terra UI defaults)",
        file=sys.stderr,
    )
    arguments = list(sys.argv[1:])
    project_root = "."
    if "--project-root" in arguments:
        position = arguments.index("--project-root")
        try:
            project_root = arguments[position + 1]
        except IndexError:
            raise SystemExit("--project-root requires a path")
        del arguments[position : position + 2]
    raise SystemExit(main(["--project-root", project_root, "gui", *arguments]))
