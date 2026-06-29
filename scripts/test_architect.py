#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Tests for the Architect interview runner with a scripted fake agent runner."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import architect


FULL_SPEC_RESPONSE = """Here is my understanding.

```json
{
  "ask_user": "Anything else?",
  "spec_updates": {
    "project": {"name": "Widget", "language": "python", "summary": "a widget"},
    "runtime": {"test": "pytest -q"},
    "requirements": [{"id": "R-001", "text": "do x", "priority": "must", "kind": "functional"}],
    "acceptance": [{"id": "A-001", "requirement": "R-001", "statement": "x works", "test_command": "pytest -q"}],
    "milestones": [{"id": "M1", "title": "first", "requirements": ["R-001"], "definition_of_done": [{"acceptance": "A-001", "check": "pytest -q"}]}],
    "risks": [{"risk": "scope", "mitigation": "freeze"}]
  },
  "open_questions": [],
  "ready_to_finalize": true
}
```
"""

PARTIAL_RESPONSE = """Let me start gathering requirements.

```json
{
  "ask_user": "What language and test command?",
  "spec_updates": {"project": {"name": "Widget"}},
  "open_questions": ["language unknown"],
  "ready_to_finalize": false
}
```
"""


class InterviewTurnTests(unittest.TestCase):
    def test_partial_then_complete(self) -> None:
        responses = [PARTIAL_RESPONSE, FULL_SPEC_RESPONSE]

        def runner(prompt_text: str) -> str:
            return responses.pop(0)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = architect.interview_turn(root, "I want a widget", runner=runner)
            self.assertEqual(first["status"], "interviewing")
            self.assertFalse(first["completeness"]["complete"])
            self.assertEqual(first["ask_user"], "What language and test command?")

            second = architect.interview_turn(root, "python, pytest -q", runner=runner)
            self.assertEqual(second["status"], "ready")
            self.assertTrue(second["completeness"]["complete"])

            # Session + artifacts persisted.
            session = architect.load_session(root)
            self.assertEqual(session["status"], "ready")
            self.assertGreaterEqual(len(session["history"]), 4)
            self.assertTrue((root / ".ai/architect/requirements.md").exists())
            self.assertTrue((root / ".ai/architect/milestones.md").exists())

    def test_not_ready_when_agent_claims_ready_but_incomplete(self) -> None:
        # Agent sets ready_to_finalize true but the spec has no milestones.
        bad = """```json
{"ask_user": "", "spec_updates": {"project": {"name": "X", "language": "py", "summary": "s"}, "runtime": {"test": "pytest"}, "requirements": [{"id": "R-001", "text": "x", "priority": "must"}], "acceptance": [{"id": "A-001", "requirement": "R-001", "statement": "ok", "test_command": "pytest"}]}, "ready_to_finalize": true}
```"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = architect.interview_turn(root, "go", runner=lambda p: bad)
            # No milestones -> deterministic checks override the agent's claim.
            self.assertEqual(result["status"], "interviewing")
            self.assertFalse(result["completeness"]["complete"])

    def test_session_resume(self) -> None:
        def runner(prompt_text: str) -> str:
            return PARTIAL_RESPONSE

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            architect.interview_turn(root, "first", runner=runner)
            session = architect.load_session(root)
            self.assertEqual(session["spec"]["project"]["name"], "Widget")
            # A second load preserves prior state and history.
            architect.interview_turn(root, "second", runner=runner)
            session2 = architect.load_session(root)
            self.assertGreater(len(session2["history"]), len(session["history"]))


if __name__ == "__main__":
    unittest.main()
