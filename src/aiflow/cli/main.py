from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from aiflow import __version__
from aiflow.skills.installer import InstallError, ProjectInstaller
from aiflow.skills.manager import SkillCollision, SkillManager, SkillValidationError


def distribution_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _root(value: str) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return Path.cwd().resolve()


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _installer(args: argparse.Namespace) -> ProjectInstaller:
    return ProjectInstaller(_root(args.project_root), distribution_root=distribution_root())


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
            user=Path.home() / ".codex" / "skills",
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


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="aiflow")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument(
        "--project-root",
        default="",
        help="explicit target Git project (defaults to current directory; environment ignored)",
    )
    commands = result.add_subparsers(dest="command", required=True)

    project = commands.add_parser("project", help="manage a project-scoped installation")
    project_actions = project.add_subparsers(dest="project_action", required=True)
    initialize = project_actions.add_parser("init")
    initialize.add_argument(
        "--profile", choices=("solo", "science", "hpc", "orchestrated", "full"),
        default="solo",
    )
    initialize.add_argument("--installation-mode", choices=("vendor", "link"), default="vendor")
    initialize.add_argument("--source-version", default="")
    project_actions.add_parser("status")
    project_actions.add_parser("verify")
    upgrade = project_actions.add_parser("upgrade")
    upgrade.add_argument(
        "--profile", choices=("solo", "science", "hpc", "orchestrated", "full"),
        required=True,
    )
    rollback = project_actions.add_parser("rollback")
    rollback.add_argument("transaction_id")
    project_actions.add_parser("uninstall")
    project.set_defaults(func=project_command)

    skills = commands.add_parser("skills", help="inspect and synchronize project skills")
    skill_actions = skills.add_subparsers(dest="skill_action", required=True)
    for action in ("list", "validate", "doctor", "sync"):
        skill_actions.add_parser(action)
    skills.set_defaults(func=skill_command)
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        return int(arguments.func(arguments))
    except (InstallError, SkillCollision, SkillValidationError) as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}), file=sys.stderr)
        return 2
