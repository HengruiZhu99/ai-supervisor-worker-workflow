#!/usr/bin/env python3
"""Scan tracked files for credential-shaped values without printing values."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.security.scan import SecretScanner  # noqa: E402


findings = SecretScanner(ROOT).scan_repository()
print(json.dumps({"ok": not findings, "findings": findings}, indent=2, sort_keys=True))
raise SystemExit(1 if findings else 0)
