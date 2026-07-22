from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class BackendDefaultRegressionTests(unittest.TestCase):
    def test_codex_is_recommended_for_every_core_role(self) -> None:
        config = json.loads(
            (ROOT / "agent_wrappers" / "codex" / "wrapper.json").read_text(encoding="utf-8")
        )
        roles = {"worker", "reviewer", "supervisor", "modulator", "chat"}
        self.assertTrue(roles.issubset(set(config["recommended_roles"])))

    def test_active_defaults_use_role_appropriate_gpt_5_6_tiers(self) -> None:
        config = json.loads(
            (ROOT / "agent_wrappers" / "codex" / "wrapper.json").read_text(encoding="utf-8")
        )
        expected = {
            "worker": "gpt-5.6-sol",
            "reviewer": "gpt-5.6-sol",
            "supervisor": "gpt-5.6-sol",
            "modulator": "gpt-5.6-sol",
            "chat": "gpt-5.6-terra",
        }
        self.assertEqual(config["default_models"], expected)
        self.assertTrue(
            {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}.issubset(config["models"])
        )

    def test_consensus_panels_default_to_codex_and_current_family(self) -> None:
        failures: list[str] = []
        for path in sorted((ROOT / "agent_wrappers" / "panels").glob("*.json")):
            panel = json.loads(path.read_text(encoding="utf-8"))
            for member in panel.get("panelists", []):
                if member.get("wrapper") != "codex":
                    failures.append(f"{path.name}:{member.get('id')}:wrapper")
                if not str(member.get("model", "")).startswith("gpt-5.6-"):
                    failures.append(f"{path.name}:{member.get('id')}:model")
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
