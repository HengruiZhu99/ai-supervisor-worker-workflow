from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / ".codex" / "agents"


class CustomAgentContractTests(unittest.TestCase):
    def test_narrow_agents_are_depth_one_codex_roles_with_explicit_permissions(
        self,
    ) -> None:
        expected = {
            "task-router": ("gpt-5.6-luna", "read-only"),
            "codebase-mapper": ("gpt-5.6-terra", "read-only"),
            "docs-researcher": ("gpt-5.6-terra", "read-only"),
            "test-architect": ("gpt-5.6-sol", "read-only"),
            "implementation-worker": ("gpt-5.6-sol", "workspace-write"),
            "scientific-reviewer": ("gpt-5.6-sol", "read-only"),
            "engineering-reviewer": ("gpt-5.6-sol", "read-only"),
            "ui-auditor": ("gpt-5.6-terra", "read-only"),
            "release-auditor": ("gpt-5.6-sol", "read-only"),
        }
        found = {path.stem for path in AGENTS.glob("*.toml")}
        self.assertEqual(found, set(expected))
        for name, (model, sandbox) in expected.items():
            payload = tomllib.loads(
                (AGENTS / f"{name}.toml").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["name"], name)
            self.assertEqual(payload["model"], model)
            self.assertEqual(payload["sandbox_mode"], sandbox)
            self.assertFalse(payload["agents"]["enabled"])
            instructions = payload["developer_instructions"].lower()
            self.assertIn("do not launch", instructions)
            self.assertIn("subagents", instructions)
            self.assertIn("do not invoke aiflow-autonomous", instructions)

    def test_project_config_uses_current_concurrency_key_and_no_default_consensus(
        self,
    ) -> None:
        payload = tomllib.loads(
            (ROOT / ".codex" / "config.toml").read_text(encoding="utf-8")
        )
        self.assertTrue(payload["agents"]["enabled"])
        self.assertEqual(payload["agents"]["max_concurrent_threads_per_session"], 4)
        self.assertNotIn("max_threads", payload["agents"])
        self.assertFalse(payload["aiflow"]["consensus_enabled"])


if __name__ == "__main__":
    unittest.main()
