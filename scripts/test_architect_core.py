#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Unit tests for the pure Architect spec logic in ``architect_core``."""

from __future__ import annotations

import json
import unittest

import architect_core as ac


def filled_spec() -> dict:
    spec = ac.new_spec()
    ac.apply_update(spec, {
        "spec_updates": {
            "project": {"name": "Widget", "language": "python", "summary": "a widget"},
            "runtime": {"test": "pytest -q"},
            "requirements": [
                {"id": "R-001", "text": "do x", "priority": "must", "kind": "functional"},
                {"id": "R-002", "text": "fast", "priority": "should", "kind": "non_functional"},
            ],
            "acceptance": [
                {"id": "A-001", "requirement": "R-001", "statement": "x works", "test_command": "pytest -q", "executable": True},
                {"id": "A-002", "requirement": "R-002", "statement": "p95 < 1s", "test_command": "pytest -q -k perf"},
            ],
            "milestones": [
                {"id": "M1", "title": "first", "requirements": ["R-001", "R-002"],
                 "definition_of_done": [{"acceptance": "A-001", "check": "pytest -q"}, {"acceptance": "A-002", "check": "pytest -q -k perf"}]},
            ],
            "risks": [{"risk": "scope creep", "mitigation": "freeze after gate"}],
        },
        "open_questions": [],
    })
    return spec


class ApplyUpdateTests(unittest.TestCase):
    def test_upsert_by_id(self) -> None:
        spec = ac.new_spec()
        ac.apply_update(spec, {"spec_updates": {"requirements": [{"id": "R-001", "text": "v1"}]}})
        ac.apply_update(spec, {"spec_updates": {"requirements": [{"id": "R-001", "text": "v2", "priority": "must"}]}})
        self.assertEqual(len(spec["requirements"]), 1)
        self.assertEqual(spec["requirements"][0]["text"], "v2")
        self.assertEqual(spec["requirements"][0]["priority"], "must")

    def test_replace_lists(self) -> None:
        spec = ac.new_spec()
        ac.apply_update(spec, {"spec_updates": {"constraints": ["a", "b"]}})
        ac.apply_update(spec, {"spec_updates": {"constraints": ["c"]}})
        self.assertEqual(spec["constraints"], ["c"])

    def test_dict_merge(self) -> None:
        spec = ac.new_spec()
        ac.apply_update(spec, {"spec_updates": {"project": {"name": "X"}}})
        ac.apply_update(spec, {"spec_updates": {"project": {"language": "go"}}})
        self.assertEqual(spec["project"]["name"], "X")
        self.assertEqual(spec["project"]["language"], "go")

    def test_open_questions_replaced(self) -> None:
        spec = ac.new_spec()
        ac.apply_update(spec, {"open_questions": ["q1", "q2"]})
        ac.apply_update(spec, {"open_questions": []})
        self.assertEqual(spec["open_questions"], [])


class ExtractUpdateTests(unittest.TestCase):
    def test_last_valid_json_block(self) -> None:
        text = """garbage
```json
{"oops": true}
```
prose
```json
{"ask_user": "q", "spec_updates": {"constraints": ["c"]}}
```
"""
        update = ac.extract_architect_update(text)
        self.assertIsNotNone(update)
        self.assertEqual(update["spec_updates"]["constraints"], ["c"])

    def test_no_block(self) -> None:
        self.assertIsNone(ac.extract_architect_update("no json here"))


class CompletenessTests(unittest.TestCase):
    def test_complete(self) -> None:
        result = ac.spec_completeness(filled_spec())
        self.assertTrue(result["complete"], result["missing"])

    def test_missing_acceptance(self) -> None:
        spec = filled_spec()
        spec["acceptance"] = [a for a in spec["acceptance"] if a["id"] != "A-001"]
        result = ac.spec_completeness(spec)
        self.assertFalse(result["complete"])
        self.assertTrue(any("R-001" in m and "acceptance" in m for m in result["missing"]))

    def test_milestone_without_dod(self) -> None:
        spec = filled_spec()
        spec["milestones"][0]["definition_of_done"] = []
        result = ac.spec_completeness(spec)
        self.assertFalse(result["complete"])
        self.assertTrue(any("Definition-of-Done" in m for m in result["missing"]))

    def test_uncovered_requirement(self) -> None:
        spec = filled_spec()
        spec["milestones"][0]["requirements"] = ["R-001"]
        result = ac.spec_completeness(spec)
        self.assertFalse(result["complete"])
        self.assertTrue(any("R-002" in m and "milestone" in m for m in result["missing"]))

    def test_dod_unknown_acceptance(self) -> None:
        spec = filled_spec()
        spec["milestones"][0]["definition_of_done"].append({"acceptance": "A-999", "check": "x"})
        result = ac.spec_completeness(spec)
        self.assertFalse(result["complete"])
        self.assertTrue(any("A-999" in m for m in result["missing"]))

    def test_open_questions_block(self) -> None:
        spec = filled_spec()
        spec["open_questions"] = ["what database?"]
        self.assertFalse(ac.spec_completeness(spec)["complete"])

    def test_missing_test_command(self) -> None:
        spec = filled_spec()
        spec["runtime"]["test"] = ""
        self.assertFalse(ac.spec_completeness(spec)["complete"])


class YamlTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        obj = ac.default_project_yaml(filled_spec())
        text = ac.dump_simple_yaml(obj)
        back = ac.parse_simple_yaml(text)
        self.assertEqual(back["runtime"]["test"], "pytest -q")
        self.assertEqual(back["project"]["name"], "Widget")
        self.assertTrue(back["consensus"]["reviewer_enabled"])
        self.assertEqual(back["budgets"]["max_attempts_per_job"], 8)

    def test_comments_and_blanks(self) -> None:
        text = "# comment\nproject:\n  name: X\n\n  language: go\n"
        parsed = ac.parse_simple_yaml(text)
        self.assertEqual(parsed["project"]["name"], "X")
        self.assertEqual(parsed["project"]["language"], "go")


class RenderTests(unittest.TestCase):
    def test_roadmap_has_machine_dod(self) -> None:
        spec = filled_spec()
        roadmap = ac.render_roadmap(spec)
        self.assertIn("definition_of_done:", roadmap)
        self.assertIn("acceptance: A-001", roadmap)

    def test_design_prompt_mentions_requirements(self) -> None:
        spec = filled_spec()
        dp = ac.render_design_prompt(spec)
        self.assertIn("R-001", dp)
        self.assertIn("Widget", dp)

    def test_autonomy_delegation_seed(self) -> None:
        spec = filled_spec()
        deleg = ac.build_autonomy_delegation(spec, delegate_milestones=1)
        self.assertTrue(deleg["active"])
        self.assertEqual(deleg["current_tranche"]["delegated_milestones"], ["M1"])
        self.assertIn("exception_triggers", deleg)
        # JSON-serializable
        json.dumps(deleg)


if __name__ == "__main__":
    unittest.main()
