from __future__ import annotations

import argparse


def add_budgets(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-wall-time", type=int, default=14_400)
    parser.add_argument("--max-tasks", type=int, default=25)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--max-idle", type=int, default=900)
    parser.add_argument("--max-agent-calls", type=int, default=50)


def add_handoff_actions(actions: argparse._SubParsersAction) -> None:
    for name in ("pause", "handoff"):
        action = actions.add_parser(name)
        action.add_argument("--run-id", default="")
    verify = actions.add_parser("verify-handoff")
    verify.add_argument("path")
