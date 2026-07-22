from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Iterable


PATTERNS = {
    "openai-key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "github-token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "aws-access-key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private-key": re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


class SecretScanner:
    def __init__(self, root: Path, *, max_file_bytes: int = 1_000_000) -> None:
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes

    def scan(self, paths: Iterable[Path]) -> list[dict[str, object]]:
        findings: list[dict[str, object]] = []
        for path in paths:
            path = path.resolve()
            try:
                if path.stat().st_size > self.max_file_bytes:
                    continue
                content = path.read_bytes()
            except OSError:
                continue
            if b"\x00" in content:
                continue
            text = content.decode("utf-8", errors="replace")
            for line_number, line in enumerate(text.splitlines(), 1):
                for name, pattern in PATTERNS.items():
                    if pattern.search(line):
                        findings.append(
                            {
                                "path": path.relative_to(self.root).as_posix(),
                                "line": line_number,
                                "pattern": name,
                            }
                        )
        return findings

    def scan_repository(self) -> list[dict[str, object]]:
        result = subprocess.run(
            ["git", "-C", str(self.root), "ls-files", "-z"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError(result.stderr.decode(errors="replace").strip() or "git ls-files failed")
        paths = [self.root / value.decode() for value in result.stdout.split(b"\0") if value]
        return self.scan(paths)
