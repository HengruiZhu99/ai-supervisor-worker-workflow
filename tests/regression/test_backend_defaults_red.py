from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class BackendDefaultRegressionTests(unittest.TestCase):
    def test_codex_is_recommended_for_every_core_role(self) -> None:
        config = json.loads(
            (ROOT / "agent_wrappers" / "codex" / "wrapper.json").read_text(
                encoding="utf-8"
            )
        )
        roles = {"worker", "reviewer", "supervisor", "modulator", "chat"}
        self.assertTrue(roles.issubset(set(config["recommended_roles"])))

    def test_active_defaults_use_role_appropriate_gpt_5_6_tiers(self) -> None:
        config = json.loads(
            (ROOT / "agent_wrappers" / "codex" / "wrapper.json").read_text(
                encoding="utf-8"
            )
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

    def test_active_launch_surfaces_do_not_default_to_cursor(self) -> None:
        paths = [
            ROOT / "scripts" / "worker_loop.sh",
            ROOT / "scripts" / "supervisor_loop.sh",
            ROOT / "scripts" / "modulator_loop.sh",
            ROOT / "scripts" / "architect.py",
            ROOT / "scripts" / "orchestrator.py",
            ROOT / "scripts" / "human_milestone_review.py",
            ROOT / "scripts" / "workflow_gui.py",
            ROOT / "project.yaml.example",
        ]
        default_cursor = re.compile(
            r":-cursor-agent|default=[\"']cursor-agent|or [\"']cursor-agent|"
            r"get\([^\n]+[\"']cursor-agent[\"']"
        )
        failures: list[str] = []
        for path in paths:
            text = path.read_text(encoding="utf-8")
            if default_cursor.search(text):
                failures.append(f"{path.relative_to(ROOT)} still defaults to Cursor")
            if "gpt-5.6-" not in text:
                failures.append(
                    f"{path.relative_to(ROOT)} has no current role model default"
                )
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
