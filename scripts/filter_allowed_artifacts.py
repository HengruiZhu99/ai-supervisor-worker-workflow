#!/usr/bin/env python3
"""Filter git status entries against declared allowed generated artifacts."""

from __future__ import annotations

import argparse
import fnmatch
from pathlib import Path


def status_path(line: str) -> str:
    if " -> " in line:
        return line.rsplit(" -> ", 1)[-1].strip()
    return line[3:].strip() if len(line) > 3 else line.strip()


def load_patterns(path: Path | None) -> list[str]:
    if not path or not path.exists():
        return []
    patterns = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def allowed(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, pattern.rstrip("/") + "/*") for pattern in patterns)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", required=True)
    parser.add_argument("--allow-file", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    status_file = Path(args.status)
    patterns = load_patterns(Path(args.allow_file) if args.allow_file else None)
    lines = status_file.read_text(encoding="utf-8", errors="replace").splitlines() if status_file.exists() else []
    unexpected = [line for line in lines if not allowed(status_path(line), patterns)]
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(unexpected) + ("\n" if unexpected else ""), encoding="utf-8")
    if unexpected:
        print(f"{len(unexpected)} unexpected dirty path(s)")
        return 1
    print("No unexpected dirty paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
