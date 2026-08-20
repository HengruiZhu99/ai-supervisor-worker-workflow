from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

from aiflow import __version__
from aiflow.agents.codex import CodexAgentBackend
from aiflow.controller.runner import Budgets, ControllerOutcome
from aiflow.identity.context import resolve_project
from aiflow.integration.transaction import GateCommands, IntegrationTransaction
from aiflow.quality.checker import QualityChecker
from aiflow.skills.installer import InstallError, ProjectInstaller
from aiflow.skills.manager import SkillCollision, SkillManager, SkillValidationError
from aiflow.skills.profiles import PROFILE_NAMES
from aiflow.controller.lifecycle import RunLifecycle
from aiflow.state.store import StateError
from aiflow.state.handoff import verify_handoff
from aiflow.cli.web import gui_command, hub_command
from aiflow.cli.permissions import permission_preflight
from aiflow.cli.release import package_command
from aiflow.cli.options import (
    add_budgets,
    add_handoff_actions,
    add_quality_commands,
    add_run_start_options,
    load_task_specs,
)


DISTRIBUTION_ROOT_OVERRIDE: Path | None = None


def distribution_root() -> Path:
    return DISTRIBUTION_ROOT_OVERRIDE or Path(__file__).resolve().parents[3]


def _root(value: str) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return Path.cwd().resolve()


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _installer(args: argparse.Namespace) -> ProjectInstaller:
    return ProjectInstaller(
        _root(args.project_root), distribution_root=distribution_root()
    )


def project_command(args: argparse.Namespace) -> int:
    installer = _installer(args)
    if args.project_action == "init":
        result = installer.init(
            args.profile,
            installation_mode=args.installation_mode,
            source_version=args.source_version,
        )
    elif args.project_action == "status":
        result = installer.status()
    elif args.project_action == "verify":
        result = installer.verify()
        _print(result)
        return 0 if result["ok"] else 3
    elif args.project_action == "upgrade":
        result = installer.upgrade(args.profile)
    elif args.project_action == "rollback":
        result = installer.rollback(args.transaction_id)
    elif args.project_action == "uninstall":
        result = installer.uninstall()
    else:  # pragma: no cover - argparse constrains this
        raise InstallError(f"unknown project action: {args.project_action}")
    _print(result)
    return 0


def skill_command(args: argparse.Namespace) -> int:
    root = _root(args.project_root)
    repository = root / ".agents" / "skills"
    if args.skill_action == "doctor":
        manager = SkillManager(
            repository=repository,
            user=Path.home() / ".agents" / "skills",
            admin=Path("/etc/codex/skills"),
            system=Path.home() / ".codex" / "plugins" / "cache",
        )
        _print(manager.doctor())
    else:
        manager = SkillManager(repository=repository)
        if args.skill_action == "list":
            _print(manager.list())
        elif args.skill_action == "validate":
            _print({"ok": True, "hashes": manager.validate()})
        elif args.skill_action == "sync":
            installer = _installer(args)
            current = installer.status()
            _print(installer.upgrade(current["profile"]))
        else:  # pragma: no cover
            raise SkillValidationError(f"unknown skills action: {args.skill_action}")
    return 0


def quality_command(args: argparse.Namespace) -> int:
    checker = QualityChecker(
        _root(args.project_root), diff_base=getattr(args, "diff_base", "HEAD")
    )
    if args.quality_action == "baseline":
        _print(checker.baseline())
        return 0
    result = checker.check()
    _print(result)
    return 0 if result["ok"] else 4


def _lifecycle(args: argparse.Namespace, *, with_backend: bool = False) -> RunLifecycle:
    context = resolve_project(explicit_root=_root(args.project_root))
    backend = None
    if with_backend and getattr(args, "backend", "codex") == "codex":
        backend = CodexAgentBackend(
            context.root,
            model=getattr(args, "model", ""),
            reasoning_effort=getattr(args, "reasoning_effort", "high"),
            timeout=getattr(args, "max_wall_time", 14_400),
        ).run
    return RunLifecycle(context, agent_backend=backend)


def _budgets(args: argparse.Namespace) -> Budgets:
    return Budgets(
        max_wall_time=args.max_wall_time,
        max_tasks=args.max_tasks,
        max_attempts=args.max_attempts,
        max_idle=args.max_idle,
        max_agent_calls=args.max_agent_calls,
    )


def _run_id(lifecycle: RunLifecycle, requested: str) -> str:
    if requested:
        return requested
    runs = lifecycle.list()
    if not runs:
        raise StateError("no project run exists")
    return str(sorted(runs, key=lambda item: item["created_at"])[-1]["run_id"])


def run_command(args: argparse.Namespace) -> int:
    lifecycle = _lifecycle(args, with_backend=args.run_action == "resume")
    result: Any
    if args.run_action == "start":
        permission_preflight(args.mode, args.parent_sandbox)
        result = lifecycle.start(
            mode=args.mode,
            objective=args.objective,
            acceptance_ids=tuple(args.acceptance_id),
            task_kind=args.task_kind,
            task_specs=load_task_specs(args.task_file),
            allowed_scope=tuple(args.allowed_scope) if not args.task_file else None,
        )
    elif args.run_action == "list":
        result = lifecycle.list()
    elif args.run_action == "verify-handoff":
        result = verify_handoff(
            Path(args.path).expanduser().resolve(), lifecycle.context
        )
    else:
        run_id = _run_id(lifecycle, args.run_id)
        if args.run_action == "status":
            result = lifecycle.status(run_id)
        elif args.run_action == "resume":
            mode = str(lifecycle.status(run_id)["mode"])
            permission_preflight(mode, args.parent_sandbox)
            result = lifecycle.resume(run_id, budgets=_budgets(args))
        elif args.run_action == "stop":
            result = lifecycle.stop(run_id)
        elif args.run_action == "pause":
            revision = int(lifecycle.status(run_id)["state_revision"])
            result = lifecycle.pause(run_id, expected_revision=revision)
        elif args.run_action == "handoff":
            revision = int(lifecycle.status(run_id)["state_revision"])
            result = lifecycle.handoff(run_id, expected_revision=revision)
        else:  # pragma: no cover
            raise StateError(f"unknown run action: {args.run_action}")
    _print(result)
    return 0


def controller_command(args: argparse.Namespace) -> int:
    permission_preflight(args.mode, args.parent_sandbox)
    lifecycle = _lifecycle(args, with_backend=True)
    if args.compat_role:
        print(
            f"warning: legacy {args.compat_role} loop is deprecated; "
            "use aiflow run start/resume",
            file=sys.stderr,
        )
    if not lifecycle.list() and not args.run_id:
        _print({"outcome": ControllerOutcome.IDLE_EXIT.value, "tasks": 0})
        return 0
    result = lifecycle.resume(_run_id(lifecycle, args.run_id), budgets=_budgets(args))
    _print(result)
    return 0


def state_command(args: argparse.Namespace) -> int:
    lifecycle = _lifecycle(args)
    run_id = _run_id(lifecycle, args.run_id)
    store = lifecycle.store(run_id)
    if args.state_action == "verify":
        store.verify()
        result: Any = {"ok": True, "run_id": run_id}
    elif args.state_action == "repair":
        result = store.repair()
    elif args.state_action == "migrate":
        result = store.migrate()
    else:  # pragma: no cover
        raise StateError(f"unknown state action: {args.state_action}")
    _print(result)
    return 0


def _integration_gates(root: Path) -> GateCommands:
    try:
        config = tomllib.loads((root / ".aiflow" / "project.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        config = {}
    commands = config.get("commands", {}) if isinstance(config, dict) else {}

    def selected(name: str) -> tuple[tuple[str, ...], ...]:
        value = commands.get(name, []) if isinstance(commands, dict) else []
        return (tuple(str(part) for part in value),) if value else ()

    quality = (
        (
            str(distribution_root() / "bin" / "aiflow"),
            "--project-root",
            ".",
            "quality",
            "check",
        ),
    )
    return GateCommands(
        focused=selected("test_focused"),
        regression=selected("test_regression"),
        quality=quality,
    )


def integrate_command(args: argparse.Namespace) -> int:
    root = _root(args.project_root)
    result = IntegrationTransaction(root, gates=_integration_gates(root)).apply(
        args.candidate, method=args.method, base_sha=args.base_sha
    )
    _print(result.__dict__)
    return 0 if result.ok else 5


def _add_web_commands(commands: argparse._SubParsersAction) -> None:
    for name, command in (("gui", gui_command), ("hub", hub_command)):
        help_text = (
            "serve the project UI"
            if name == "gui"
            else "serve the read-only project hub"
        )
        web = commands.add_parser(name, help=help_text)
        web.add_argument("--host", default="127.0.0.1")
        web.add_argument("--port", type=int, default=0)
        web.add_argument("--allow-remote", action="store_true")
        web.add_argument("--no-open", action="store_true")
        web.add_argument("--check", action="store_true")
        if name == "hub":
            web.add_argument("--project", action="append", default=[])
        web.set_defaults(func=command)


def _add_package_commands(commands: argparse._SubParsersAction) -> None:
    package = commands.add_parser("package", help="build or verify an offline zipapp")
    actions = package.add_subparsers(dest="package_action", required=True)
    build = actions.add_parser("build")
    build.add_argument("--distribution-root", default=str(distribution_root()))
    build.add_argument("--output-dir", default="dist")
    verify = actions.add_parser("verify")
    verify.add_argument("artifact")
    package.set_defaults(func=package_command)


def _add_run_commands(commands: argparse._SubParsersAction) -> None:
    runs = commands.add_parser("run", help="create and control durable project runs")
    actions = runs.add_subparsers(dest="run_action", required=True)
    start = actions.add_parser("start")
    add_run_start_options(start)
    actions.add_parser("list")
    status = actions.add_parser("status")
    status.add_argument("--run-id", default="")
    resume = actions.add_parser("resume")
    resume.add_argument("--run-id", default="")
    resume.add_argument(
        "--parent-sandbox",
        choices=("read-only", "workspace-write", "danger-full-access"),
        default="",
    )
    add_budgets(resume)
    resume.add_argument("--backend", choices=("codex", "none"), default="codex")
    resume.add_argument(
        "--model", default="", help="override role-appropriate GPT-5.6 defaults"
    )
    resume.add_argument("--reasoning-effort", default="high")
    stop = actions.add_parser("stop")
    stop.add_argument("--run-id", default="")
    add_handoff_actions(actions)
    runs.set_defaults(func=run_command)


def _add_controller_command(commands: argparse._SubParsersAction) -> None:
    controller = commands.add_parser(
        "controller", help="run the finite deterministic controller"
    )
    actions = controller.add_subparsers(dest="controller_action", required=True)
    run = actions.add_parser("run")
    run.add_argument("--run-id", default="")
    run.add_argument("--mode", choices=("solo", "orchestrated"), default="solo")
    run.add_argument("--compat-role", default="")
    run.add_argument(
        "--parent-sandbox",
        choices=("read-only", "workspace-write", "danger-full-access"),
        default="",
    )
    add_budgets(run)
    run.add_argument("--backend", choices=("codex", "none"), default="codex")
    run.add_argument(
        "--model", default="", help="override role-appropriate GPT-5.6 defaults"
    )
    run.add_argument("--reasoning-effort", default="high")
    controller.set_defaults(func=controller_command)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="aiflow")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument(
        "--project-root",
        default="",
        help="explicit target Git project (defaults to current directory; environment ignored)",
    )
    commands = result.add_subparsers(dest="command", required=True)

    project = commands.add_parser(
        "project", help="manage a project-scoped installation"
    )
    project_actions = project.add_subparsers(dest="project_action", required=True)
    initialize = project_actions.add_parser("init")
    initialize.add_argument(
        "--profile",
        choices=PROFILE_NAMES,
        default="solo",
    )
    initialize.add_argument(
        "--installation-mode", choices=("vendor", "link"), default="vendor"
    )
    initialize.add_argument("--source-version", default="")
    project_actions.add_parser("status")
    project_actions.add_parser("verify")
    upgrade = project_actions.add_parser("upgrade")
    upgrade.add_argument(
        "--profile",
        choices=PROFILE_NAMES,
        required=True,
    )
    rollback = project_actions.add_parser("rollback")
    rollback.add_argument("transaction_id")
    project_actions.add_parser("uninstall")
    project.set_defaults(func=project_command)

    skills = commands.add_parser(
        "skills", help="inspect and synchronize project skills"
    )
    skill_actions = skills.add_subparsers(dest="skill_action", required=True)
    for action in ("list", "validate", "doctor", "sync"):
        skill_actions.add_parser(action)
    skills.set_defaults(func=skill_command)

    add_quality_commands(commands, quality_command)

    _add_run_commands(commands)
    _add_controller_command(commands)

    state = commands.add_parser(
        "state", help="verify, repair, or migrate canonical state"
    )
    state_actions = state.add_subparsers(dest="state_action", required=True)
    for action in ("verify", "repair", "migrate"):
        state_parser = state_actions.add_parser(action)
        state_parser.add_argument("--run-id", default="")
    state.set_defaults(func=state_command)

    integrate = commands.add_parser(
        "integrate", help="validate and atomically apply a candidate"
    )
    integrate.add_argument("--candidate", required=True)
    integrate.add_argument("--base-sha", default="")
    integrate.add_argument(
        "--method", choices=("merge", "cherry-pick"), default="merge"
    )
    integrate.set_defaults(func=integrate_command)

    _add_web_commands(commands)

    _add_package_commands(commands)
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        return int(arguments.func(arguments))
    except (
        InstallError,
        SkillCollision,
        SkillValidationError,
        StateError,
        ValueError,
    ) as exc:
        print(
            json.dumps({"error": str(exc), "type": type(exc).__name__}), file=sys.stderr
        )
        return 2
