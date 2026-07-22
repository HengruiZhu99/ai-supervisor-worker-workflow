from __future__ import annotations

import json
import hashlib
import re
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
from aiflow.skills.install_io import (
    InstallError,
    atomic_bytes as _atomic_bytes,
    json_bytes as _json_bytes,
    project_config,
    write_atomic as _write_atomic,
)
from aiflow.skills.profiles import ProfileError, profile_skills as _profile_skills


def profile_skills(profile: str) -> tuple[str, ...]:
    try:
        return _profile_skills(profile)
    except ProfileError as exc:
        raise InstallError(str(exc)) from exc


SAFE_TRANSACTION = re.compile(r"^[0-9]{8}T[0-9]{6}\.[0-9]{6}Z$")
SAFE_CHECKSUM = re.compile(r"^[a-f0-9]{64}$")
MUTABLE_CONFIG = ".aiflow/project.toml"


class ProjectInstaller:
    def __init__(self, root: Path, *, distribution_root: Path) -> None:
        self.root = root.resolve()
        self.distribution_root = distribution_root.resolve()
        self.config_dir = self.root / ".aiflow"
        self.lock_file = self.config_dir / "project.lock"
        self.skill_source = self.distribution_root / ".agents" / "skills"

    def _relative(self, value: str) -> str:
        path = Path(value)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise InstallError(f"unsafe managed path in project lock: {value!r}")
        normalized = path.as_posix()
        target = self.root / path
        current = self.root
        for part in path.parts:
            current = current / part
            if current.is_symlink():
                raise InstallError(f"managed path crosses a symlink: {normalized}")
        if self.root not in target.resolve(strict=False).parents:
            raise InstallError(f"managed path escapes project root: {normalized}")
        return normalized

    def _path(self, relative: str) -> Path:
        return self.root / self._relative(relative)

    def _validate_lock(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or int(payload.get("schema_version", 0)) != 1:
            raise InstallError("project lock must be a schema-version 1 object")
        lock = dict(payload)
        for field in ("profile", "workflow_version", "installation_mode"):
            if not isinstance(lock.get(field), str) or not lock[field]:
                raise InstallError(f"project lock lacks {field}")
        managed = lock.get("managed_files", {})
        mutable = lock.get("mutable_files", {})
        if not isinstance(managed, dict) or not isinstance(mutable, dict):
            raise InstallError("project lock file ownership maps must be objects")
        clean_managed = self._validated_hashes(managed)
        clean_mutable = self._validated_hashes(mutable)
        if MUTABLE_CONFIG in clean_managed:
            clean_mutable.setdefault(MUTABLE_CONFIG, clean_managed.pop(MUTABLE_CONFIG))
        if set(clean_managed) & set(clean_mutable):
            raise InstallError("project lock has duplicate managed/mutable ownership")
        lock["managed_files"] = clean_managed
        lock["mutable_files"] = clean_mutable
        return lock

    def _validated_hashes(self, values: dict[Any, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        for relative, checksum in values.items():
            normalized = self._relative(str(relative))
            if not SAFE_CHECKSUM.fullmatch(str(checksum)):
                raise InstallError(f"invalid managed checksum for {normalized}")
            result[normalized] = str(checksum)
        return result

    def _read_lock(self) -> dict[str, Any]:
        try:
            return self._validate_lock(
                json.loads(self.lock_file.read_text(encoding="utf-8"))
            )
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
        except (
            FileNotFoundError,
            OSError,
            KeyError,
            ValueError,
            tomllib.TOMLDecodeError,
        ):
            return str(uuid.uuid4())

    def _project_config(self, profile: str, project_id: str) -> bytes:
        return project_config(self.root, self.config_dir, profile, project_id)

    def _desired(self, profile: str, project_id: str) -> dict[str, bytes]:
        desired: dict[str, bytes] = {
            ".aiflow/handoffs/.gitkeep": b"",
            MUTABLE_CONFIG: self._project_config(profile, project_id),
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
                "modules = []\n\n"
                "[storage]\n"
                'scratch_root = ""\n'
                'persistent_root = ""\n'
            ).encode()
        for skill_name in profile_skills(profile):
            source = self.skill_source / skill_name
            if not (source / "SKILL.md").is_file():
                raise InstallError(
                    f"profile {profile} requires unavailable skill: {skill_name}"
                )
            for path in sorted(item for item in source.rglob("*") if item.is_file()):
                relative = (
                    Path(".agents/skills") / skill_name / path.relative_to(source)
                )
                desired[relative.as_posix()] = path.read_bytes()
        if profile in {"orchestrated", "full"}:
            codex_source = self.distribution_root / ".codex"
            for path in sorted(
                item for item in codex_source.rglob("*.toml") if item.is_file()
            ):
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
            relative: hashlib.sha256(content).hexdigest()
            for relative, content in sorted(desired.items())
            if relative != MUTABLE_CONFIG
        }
        skill_hashes: dict[str, str] = {}
        for name in profile_skills(profile):
            prefix = f".agents/skills/{name}/"
            digest = hashlib.sha256()
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
            "mutable_files": {
                MUTABLE_CONFIG: hashlib.sha256(desired[MUTABLE_CONFIG]).hexdigest()
            },
        }

    @staticmethod
    def _owned(lock: dict[str, Any]) -> dict[str, str]:
        return {**lock.get("managed_files", {}), **lock.get("mutable_files", {})}

    def _preflight(
        self, desired: dict[str, bytes], previous: dict[str, Any] | None
    ) -> None:
        old_owned = self._owned(previous or {})
        for relative in desired:
            target = self._path(relative)
            if (
                target.exists()
                and relative not in old_owned
                and relative != MUTABLE_CONFIG
            ):
                raise InstallError(
                    f"refusing to overwrite unowned pre-existing file: {relative}"
                )
        if previous:
            verification = self.verify()
            if verification["missing"] or verification["modified"]:
                raise InstallError(
                    "managed files have drift; refusing transactional overwrite"
                )

    def _snapshots(self, paths: set[str]) -> dict[str, bytes | None]:
        snapshots: dict[str, bytes | None] = {}
        for relative in paths:
            target = self._path(relative)
            snapshots[relative] = target.read_bytes() if target.is_file() else None
        return snapshots

    def _restore(self, snapshots: dict[str, bytes | None]) -> None:
        for relative, content in snapshots.items():
            target = self._path(relative)
            if content is None:
                if target.is_file():
                    target.unlink()
            else:
                _write_atomic(target, content)
        self._prune_empty_dirs()

    def _prune_empty_dirs(self) -> None:
        roots = (self.root / ".agents", self.root / ".codex", self.config_dir)
        for base in roots:
            directories = (
                sorted(
                    (path for path in base.rglob("*") if path.is_dir()),
                    reverse=True,
                )
                if base.exists()
                else []
            )
            for directory in directories:
                try:
                    directory.rmdir()
                except OSError:
                    pass

    def _apply(
        self,
        desired: dict[str, bytes],
        lock: dict[str, Any],
        previous: dict[str, Any] | None,
    ) -> None:
        self._preflight(desired, previous)
        old_owned = self._owned(previous or {})
        affected = set(desired) | set(old_owned) | {".aiflow/project.lock"}
        snapshots = self._snapshots(affected)
        with tempfile.TemporaryDirectory(
            prefix=".aiflow-install-stage-", dir=self.root
        ) as temporary:
            stage = Path(temporary)
            for relative, content in desired.items():
                _write_atomic(stage / relative, content)
            try:
                for relative, content in desired.items():
                    _atomic_bytes(self._path(relative), content)
                for relative, checksum in old_owned.items():
                    if relative in desired:
                        continue
                    target = self._path(relative)
                    if target.is_file() and file_hash(target) == checksum:
                        target.unlink()
                    elif target.exists():
                        raise InstallError(
                            f"obsolete managed file changed during upgrade: {relative}"
                        )
                _atomic_bytes(self.lock_file, _json_bytes(lock))
            except Exception:
                self._restore(snapshots)
                raise
        self._prune_empty_dirs()

    def _install(
        self,
        profile: str,
        *,
        installation_mode: str,
        source_version: str,
        previous: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if installation_mode not in {"vendor", "link"}:
            raise InstallError(f"unknown installation mode: {installation_mode}")
        if installation_mode == "link" and not source_version:
            raise InstallError(
                "link mode requires an explicit immutable source version"
            )
        if installation_mode == "link":
            raise InstallError(
                "link mode is local-only and unavailable from a mutable source tree"
            )
        desired = self._desired(profile, self._project_id())
        lock = self._make_lock(
            profile=profile,
            mode=installation_mode,
            desired=desired,
            source_version=source_version or __version__,
        )
        self._apply(desired, lock, previous)
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
            if (
                lock.get("profile") == profile
                and lock.get("installation_mode") == installation_mode
            ):
                if not verification["ok"]:
                    raise InstallError(
                        "existing managed files have drift; refusing idempotent overwrite"
                    )
                return self.status()
            raise InstallError(
                "project already initialized with a different profile; use upgrade"
            )
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
        for relative, expected in lock["managed_files"].items():
            path = self._path(relative)
            if not path.is_file():
                missing.append(relative)
            elif file_hash(path) != expected:
                modified.append(relative)
        for relative in lock["mutable_files"]:
            if not self._path(relative).is_file():
                missing.append(relative)
        return {
            "ok": not missing and not modified,
            "missing": missing,
            "modified": modified,
        }

    def _backup(self, transaction_id: str) -> Path:
        lock = self._read_lock()
        backup = self.config_dir / "backups" / transaction_id
        if backup.exists():
            raise InstallError(f"backup transaction already exists: {transaction_id}")
        files = sorted(self._owned(lock))
        for relative in files:
            source = self._path(relative)
            if source.is_file():
                destination = backup / "files" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        backup.mkdir(parents=True, exist_ok=True)
        _atomic_bytes(backup / "project.lock", self.lock_file.read_bytes())
        _atomic_bytes(backup / "manifest.json", _json_bytes({"managed_files": files}))
        return backup

    def upgrade(self, profile: str) -> dict[str, Any]:
        current = self._read_lock()
        verification = self.verify()
        self_hosted_distribution = self.root == self.distribution_root
        if not verification["ok"] and not self_hosted_distribution:
            raise InstallError("managed files have drift; refusing upgrade")
        transaction_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = self._backup(transaction_id)
        try:
            status = self._install(
                profile,
                installation_mode="vendor",
                source_version=__version__,
                previous=current,
            )
        except Exception:
            raise
        return {**status, "transaction_id": transaction_id, "backup": str(backup)}

    def rollback(self, transaction_id: str) -> dict[str, Any]:
        if not SAFE_TRANSACTION.fullmatch(transaction_id):
            raise InstallError(f"invalid rollback transaction ID: {transaction_id!r}")
        backup = self.config_dir / "backups" / transaction_id
        try:
            previous_lock = self._validate_lock(
                json.loads((backup / "project.lock").read_text(encoding="utf-8"))
            )
        except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            raise InstallError(
                f"invalid rollback transaction {transaction_id}: {exc}"
            ) from exc
        current = self._read_lock()
        verification = self.verify()
        mutable_drift = [
            relative
            for relative, checksum in current["mutable_files"].items()
            if self._path(relative).is_file()
            and file_hash(self._path(relative)) != checksum
        ]
        if verification["missing"] or verification["modified"] or mutable_drift:
            raise InstallError("post-upgrade drift prevents safe rollback")
        previous_files = set(self._owned(previous_lock))
        desired = {}
        for relative in previous_files:
            source = backup / "files" / relative
            if source.is_file():
                desired[relative] = source.read_bytes()
        self._apply(desired, previous_lock, current)
        return self.status()

    def uninstall(self) -> dict[str, Any]:
        lock = self._read_lock()
        removed: list[str] = []
        preserved: list[str] = []
        for relative, expected in sorted(self._owned(lock).items(), reverse=True):
            path = self._path(relative)
            if not path.exists():
                continue
            if path.is_file() and file_hash(path) == expected:
                path.unlink()
                removed.append(relative)
            else:
                preserved.append(relative)
        self.lock_file.unlink(missing_ok=True)
        self._prune_empty_dirs()
        return {"removed": sorted(removed), "preserved_modified": sorted(preserved)}
