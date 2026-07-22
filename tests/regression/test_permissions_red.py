from __future__ import annotations

import argparse
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]


def load_agent_wrapper():
    spec = importlib.util.spec_from_file_location(
        "legacy_agent_wrapper", ROOT / "scripts" / "agent_wrapper.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CodexPermissionRegressionTests(unittest.TestCase):
    def command_for(self, role: str, *, read_only: bool = False) -> list[str]:
        module = load_agent_wrapper()
        with tempfile.TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "prompt.md"
            prompt.write_text("bounded task\n", encoding="utf-8")
            args = argparse.Namespace(
                role=role,
                workspace=tmp,
                prompt_file=str(prompt),
                model="",
                reasoning_effort="",
                extra_args="",
                read_only=read_only,
            )
            completed = module.subprocess.CompletedProcess([], 0, "", "")
            with mock.patch.object(module, "run_owned_process", return_value=completed) as call:
                module.run_codex(args)
            return list(call.call_args.args[0])

    def test_read_only_role_never_requests_full_access(self) -> None:
        command = self.command_for("reviewer", read_only=True)
        sandbox = command[command.index("--sandbox") + 1]
        self.assertEqual(sandbox, "read-only", command)
        self.assertNotIn("danger-full-access", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)

    def test_writer_uses_explicit_bounded_permissions(self) -> None:
        command = self.command_for("worker")
        self.assertEqual(command[command.index("--sandbox") + 1], "workspace-write")
        self.assertIn("--ask-for-approval", command)
        self.assertNotIn("danger-full-access", command)

    def test_unrestricted_parent_preflight_is_available(self) -> None:
        module = load_agent_wrapper()
        self.assertTrue(
            hasattr(module, "validate_parent_permissions"),
            "orchestrated mode has no parent permission preflight",
        )


if __name__ == "__main__":
    unittest.main()
