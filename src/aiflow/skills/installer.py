from __future__ import annotations

import json
import os
import shutil
import tempfile
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiflow import __version__
from aiflow.quality.config import DEFAULT_DEPRECATIONS_TOML, DEFAULT_QUALITY_TOML
from aiflow.skills.manager import file_hash


class InstallError(RuntimeError):
    """A project installation cannot proceed without risking user files."""


PROFILE_ADDITIONS: dict[str, tuple[str, ...]] = {
    "solo": (
        "tdd-solo",
        "systematic-debugging",
        "verification-before-completion",
    ),
    "science": (
        "numerical-test-design",
        "scientific-code-review",
        "paper-equation-implementation",
        "experiment-provenance",
        "performance-portability-review",
    ),
    "hpc": (
        "hpc-job-monitor",
        "hpc-job-triage",
        "cluster-portability",
    ),
    "orchestrated": (
        "grill-me-nr",
        "tdd-nr",
        "handoff-nr",
        "aiflow-autonomous",
    ),
    "full": (
        "experiment-sweep",
        "gui-ux-audit",
        "release-readiness",
    ),
}


def profile_skills(profile: str) -> tuple[str, ...]:
    if profile not in PROFILE_ADDITIONS:
        raise InstallError(f"unknown project profile: {profile}")
    parents = {
        "solo": (),
        "science": ("solo",),
        "hpc": ("science",),
        "orchestrated": ("science",),
        "full": ("hpc", "orchestrated"),
    }
    result: list[str] = []
    for parent in parents[profile]:
        result.extend(profile_skills(parent))
    result.extend(PROFILE_ADDITIONS[profile])
    return tuple(dict.fromkeys(result))


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


class ProjectInstaller:
    def __init__(self, root: Path, *, distribution_root: Path) -> None:
        self.root = root.resolve()
        self.distribution_root = distribution_root.resolve()
        self.config_dir = self.root / ".aiflow"
        self.lock_file = self.config_dir / "project.lock"
        self.skill_source = self.distribution_root / ".agents" / "skills"

    def _read_lock(self) -> dict[str, Any]:
        try:
            return json.loads(self.lock_file.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise InstallError(f"project is not initialized: {self.root}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise InstallError(f"invalid project lock: {exc}") from exc

    def _project_id(self) -> str:
        config = self.config_dir / "project.toml"
        try:
            payload = tomllib.loads(config.read_text(encoding="utf-8"))
            value = str(payload["project_id"])
            uuid.UUID(value)
            return value
        except (FileNotFoundError, OSError, KeyError, ValueError, tomllib.TOMLDecodeError):
            return str(uuid.uuid4())

    def _desired(self, profile: str, project_id: str) -> dict[str, bytes]:
        desired: dict[str, bytes] = {
            ".aiflow/handoffs/.gitkeep": b"",
            ".aiflow/project.toml": (
                "schema_version = 1\n"
                f'project_id = "{project_id}"\n'
                f'name = "{self.root.name}"\n'
                f'profile = "{profile}"\n\n'
                "[commands]\n"
                "build = []\n"
                "test_focused = []\n"
                "test_regression = []\n\n"
                "[execution]\n"
                "allow_parallel_mutating_runs = false\n"
                'default_mode = "solo"\n'
                "max_wall_time_seconds = 14400\n"
                "max_idle_seconds = 900\n"
                "max_attempts_per_task = 3\n\n"
                "[gui]\n"
                'bind = "127.0.0.1"\n'
            ).encode(),
        }
        desired[".aiflow/quality.toml"] = DEFAULT_QUALITY_TOML.encode()
        deprecations = (
            DEFAULT_DEPRECATIONS_TOML
            if self.root == self.distribution_root
            else "schema_version = 1\n"
        )
        desired[".aiflow/deprecations.toml"] = deprecations.encode()
        if profile in {"hpc", "full"}:
            desired[".aiflow/site.toml"] = (
                "schema_version = 1\n\n"
                "[scheduler]\n"
                'kind = "auto"\n'
                "monitor_read_only = true\n"
                "min_poll_seconds = 5\n\n"
                "[environment]\n"
                'setup_script = ""\n'
                'modules = []\n\n'
                "[storage]\n"
                'scratch_root = ""\n'
                'persistent_root = ""\n'
            ).encode()
        for skill_name in profile_skills(profile):
            source = self.skill_source / skill_name
            if not (source / "SKILL.md").is_file():
                raise InstallError(f"profile {profile} requires unavailable skill: {skill_name}")
            for path in sorted(item for item in source.rglob("*") if item.is_file()):
                relative = Path(".agents/skills") / skill_name / path.relative_to(source)
                desired[relative.as_posix()] = path.read_bytes()
        if profile in {"orchestrated", "full"}:
            codex_source = self.distribution_root / ".codex"
            for path in sorted(item for item in codex_source.rglob("*.toml") if item.is_file()):
                relative = Path(".codex") / path.relative_to(codex_source)
                desired[relative.as_posix()] = path.read_bytes()
        return desired

    def _make_lock(
        self,
        *,
        profile: str,
        mode: str,
        desired: dict[str, bytes],
        source_version: str,
    ) -> dict[str, Any]:
        managed = {
            relative: __import__("hashlib").sha256(content).hexdigest()
            for relative, content in sorted(desired.items())
        }
        skill_hashes: dict[str, str] = {}
        for name in profile_skills(profile):
            prefix = f".agents/skills/{name}/"
            digest = __import__("hashlib").sha256()
            for relative, checksum in managed.items():
                if relative.startswith(prefix):
                    digest.update(relative.removeprefix(prefix).encode())
                    digest.update(b"\0")
                    digest.update(checksum.encode())
                    digest.update(b"\0")
            skill_hashes[name] = digest.hexdigest()
        agent_hashes = {
            Path(relative).stem: checksum
            for relative, checksum in managed.items()
            if relative.startswith(".codex/agents/") and relative.endswith(".toml")
        }
        return {
            "schema_version": 1,
            "workflow_version": __version__,
            "source_version": source_version,
            "profile": profile,
            "installation_mode": mode,
            "skill_hashes": skill_hashes,
            "custom_agent_hashes": agent_hashes,
            "managed_files": managed,
        }

    def _install(
        self,
        profile: str,
        *,
        installation_mode: str,
        source_version: str,
    ) -> dict[str, Any]:
        if installation_mode not in {"vendor", "link"}:
            raise InstallError(f"unknown installation mode: {installation_mode}")
        if installation_mode == "link" and not source_version:
            raise InstallError("link mode requires an explicit immutable source version")
        if installation_mode == "link":
            raise InstallError("link mode is local-only and unavailable from a mutable source tree")
        desired = self._desired(profile, self._project_id())
        lock = self._make_lock(
            profile=profile,
            mode=installation_mode,
            desired=desired,
            source_version=source_version or __version__,
        )
        for relative, content in desired.items():
            _atomic_bytes(self.root / relative, content)
        (self.config_dir / "handoffs").mkdir(parents=True, exist_ok=True)
        _atomic_bytes(self.lock_file, _json_bytes(lock))
        return self.status()

    def init(
        self,
        profile: str = "solo",
        *,
        installation_mode: str = "vendor",
        source_version: str = "",
    ) -> dict[str, Any]:
        if self.lock_file.exists():
            lock = self._read_lock()
            verification = self.verify()
            if lock.get("profile") == profile and lock.get("installation_mode") == installation_mode:
                if not verification["ok"]:
                    raise InstallError("existing managed files have drift; refusing idempotent overwrite")
                return self.status()
            raise InstallError("project already initialized with a different profile; use upgrade")
        return self._install(
            profile, installation_mode=installation_mode, source_version=source_version
        )

    def status(self) -> dict[str, Any]:
        lock = self._read_lock()
        verification = self.verify()
        return {
            "project_root": str(self.root),
            "profile": lock["profile"],
            "workflow_version": lock["workflow_version"],
            "installation_mode": lock["installation_mode"],
            **verification,
        }

    def verify(self) -> dict[str, Any]:
        lock = self._read_lock()
        missing: list[str] = []
        modified: list[str] = []
        for relative, expected in lock.get("managed_files", {}).items():
            path = self.root / relative
            if not path.is_file():
                missing.append(relative)
            elif file_hash(path) != expected:
                modified.append(relative)
        return {"ok": not missing and not modified, "missing": missing, "modified": modified}

    def _backup(self, transaction_id: str) -> Path:
        lock = self._read_lock()
        backup = self.config_dir / "backups" / transaction_id
        if backup.exists():
            raise InstallError(f"backup transaction already exists: {transaction_id}")
        files = sorted(lock["managed_files"])
        for relative in files:
            source = self.root / relative
            if source.is_file():
                destination = backup / "files" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        backup.mkdir(parents=True, exist_ok=True)
        _atomic_bytes(backup / "project.lock", self.lock_file.read_bytes())
        _atomic_bytes(backup / "manifest.json", _json_bytes({"managed_files": files}))
        return backup

    def upgrade(self, profile: str) -> dict[str, Any]:
        verification = self.verify()
        self_hosted_distribution = self.root == self.distribution_root
        if not verification["ok"] and not self_hosted_distribution:
            raise InstallError("managed files have drift; refusing upgrade")
        transaction_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = self._backup(transaction_id)
        try:
            status = self._install(
                profile, installation_mode="vendor", source_version=__version__
            )
        except Exception:
            self.rollback(transaction_id)
            raise
        return {**status, "transaction_id": transaction_id, "backup": str(backup)}

    def rollback(self, transaction_id: str) -> dict[str, Any]:
        backup = self.config_dir / "backups" / transaction_id
        try:
            previous_lock = json.loads((backup / "project.lock").read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            raise InstallError(f"invalid rollback transaction {transaction_id}: {exc}") from exc
        current = self._read_lock()
        previous_files = set(previous_lock["managed_files"])
        for relative in current["managed_files"]:
            if relative not in previous_files:
                path = self.root / relative
                if path.is_file() and file_hash(path) == current["managed_files"][relative]:
                    path.unlink()
        for relative in previous_files:
            source = backup / "files" / relative
            if source.is_file():
                _atomic_bytes(self.root / relative, source.read_bytes())
        _atomic_bytes(self.lock_file, _json_bytes(previous_lock))
        return self.status()

    def uninstall(self) -> dict[str, Any]:
        lock = self._read_lock()
        removed: list[str] = []
        preserved: list[str] = []
        for relative, expected in sorted(lock["managed_files"].items(), reverse=True):
            path = self.root / relative
            if not path.exists():
                continue
            if path.is_file() and file_hash(path) == expected:
                path.unlink()
                removed.append(relative)
            else:
                preserved.append(relative)
        self.lock_file.unlink(missing_ok=True)
        for root in (self.root / ".agents" / "skills", self.config_dir / "handoffs"):
            for directory in sorted((path for path in root.rglob("*") if path.is_dir()), reverse=True) if root.exists() else []:
                try:
                    directory.rmdir()
                except OSError:
                    pass
        return {"removed": sorted(removed), "preserved_modified": sorted(preserved)}
