from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class FrontendContractTests(unittest.TestCase):
    def test_react_typescript_source_and_node_free_built_assets_are_present(self) -> None:
        package = json.loads((ROOT / "frontend" / "package.json").read_text())
        source = (ROOT / "frontend" / "src" / "main.tsx").read_text()
        built = (ROOT / "src" / "aiflow" / "api" / "static" / "app.js").read_text()
        self.assertIn("react", package["dependencies"])
        self.assertIn("typescript", package["devDependencies"])
        self.assertIn("createRoot", source)
        self.assertIn("EventSource", source)
        self.assertIn("EventSource", built)
        self.assertNotIn("from \"react\"", built)

    def test_progressive_disclosure_identity_and_accessibility_are_source_contracts(self) -> None:
        source = (ROOT / "frontend" / "src" / "main.tsx").read_text()
        for marker in (
            'id="project-identity"',
            "Solo TDD",
            "Autonomous Program",
            "Advanced contract settings",
            "skip-link",
            "aria-label",
            "role=\"status\"",
            "Export handoff",
            '>Resume</button>',
            '>Pause</button>',
        ):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
