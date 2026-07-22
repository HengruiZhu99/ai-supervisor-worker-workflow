from __future__ import annotations

import os
import re
import shlex
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class DocumentedCliTests(unittest.TestCase):
    def test_marked_read_only_examples_execute_successfully(self) -> None:
        reference = (ROOT / "docs" / "CLI_REFERENCE.md").read_text()
        commands = re.findall(r"<!-- cli-check: (.+?) -->", reference)
        self.assertGreaterEqual(len(commands), 7)
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        for command in commands:
            with self.subTest(command=command):
                arguments = shlex.split(command)
                if arguments[0] == "aiflow":
                    arguments[0] = str(ROOT / "bin" / "aiflow")
                result = subprocess.run(
                    arguments,
                    cwd=ROOT,
                    env=environment,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
