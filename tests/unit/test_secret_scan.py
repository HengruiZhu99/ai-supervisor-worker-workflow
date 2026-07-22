from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aiflow.security.scan import SecretScanner


ROOT = Path(__file__).resolve().parents[2]


class SecretScanTests(unittest.TestCase):
    def test_detects_known_secret_shapes_without_echoing_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "ghp_" + "A" * 36
            unsafe = root / "unsafe.txt"
            unsafe.write_text(f"credential={secret}\n")
            findings = SecretScanner(root).scan([unsafe])
            self.assertEqual(findings[0]["pattern"], "github-token")
            self.assertEqual(findings[0]["line"], 1)
            self.assertNotIn(secret, repr(findings))

    def test_binary_and_large_files_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "binary.bin"
            binary.write_bytes(b"\x00ghp_" + b"A" * 36)
            large = root / "large.txt"
            large.write_text("x" * 2048)
            scanner = SecretScanner(root, max_file_bytes=1024)
            self.assertEqual(scanner.scan([binary, large]), [])

    def test_current_tracked_repository_has_no_secret_shapes(self) -> None:
        self.assertEqual(SecretScanner(ROOT).scan_repository(), [])


if __name__ == "__main__":
    unittest.main()
