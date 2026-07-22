from __future__ import annotations

import json
import os
import subprocess
import tempfile
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class IdentityError(RuntimeError):
    """Base identity error."""


class ProjectConfigError(IdentityError):
    """The project contract is absent or invalid."""


class IdentityCollision(IdentityError):
    """One checkout ID appears at multiple live Git common directories."""


class ThreadIdentityMismatch(IdentityError):
    """A Codex thread does not belong to the requested run/worktree."""


@dataclass(frozen=True)
class ProjectContext:
    root: Path
    git_common_dir: Path
    git_dir: Path
    project_id: str
    checkout_id: str
    worktree_id: str

    @property
    def state_root(self) -> Path:
        return self.git_common_dir / "aiflow"

    def identity_fields(self, run_id: str = "") -> dict[str, str]:
        fields = {
            "project_id": self.project_id,
            "checkout_id": self.checkout_id,
            "worktree_id": self.worktree_id,
        }
        if run_id:
            fields["run_id"] = run_id
        return fields


def _run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        detail = result.stderr.strip() or "not a Git repository"
        raise IdentityError(f"cannot resolve Git identity for {root}: {detail}")
    return result.stdout.strip()


def _git_path(root: Path, option: str) -> Path:
    raw = Path(_run_git(root, "rev-parse", option))
    return (raw if raw.is_absolute() else root / raw).resolve()


def _project_root(explicit_root: Path | str | None, cwd: Path | None) -> Path:
    start = Path(explicit_root).expanduser() if explicit_root else (cwd or Path.cwd())
    return Path(_run_git(start.resolve(), "rev-parse", "--show-toplevel")).resolve()


def _project_id(root: Path) -> str:
    config = root / ".aiflow" / "project.toml"
    try:
        payload = tomllib.loads(config.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProjectConfigError(f"missing canonical project config: {config}") from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProjectConfigError(f"invalid project config {config}: {exc}") from exc
    project_id = str(payload.get("project_id", "")).strip()
    if not project_id:
        raise ProjectConfigError(f"project_id is required in {config}")
    return project_id


def _read_or_create_id(path: Path) -> str:
    try:
        existing = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""
    if existing:
        try:
            uuid.UUID(existing)
        except ValueError as exc:
            raise IdentityError(f"invalid UUID in {path}: {existing!r}") from exc
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    value = str(uuid.uuid4())
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _read_or_create_id(path)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(value + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return value


def resolve_project(
    *,
    explicit_root: Path | str | None = None,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> ProjectContext:
    """Resolve explicit root or current Git repository; inherited AIFLOW_* is ignored."""
    values = os.environ if env is None else env
    root = _project_root(explicit_root, cwd)
    common = _git_path(root, "--git-common-dir")
    git_dir = _git_path(root, "--git-dir")
    context = ProjectContext(
        root=root,
        git_common_dir=common,
        git_dir=git_dir,
        project_id=_project_id(root),
        checkout_id=_read_or_create_id(common / "aiflow" / "checkout-id"),
        worktree_id=_read_or_create_id(git_dir / "aiflow" / "worktree-id"),
    )
    CheckoutRegistry(_registry_path(values)).register(context.checkout_id, common)
    return context


def _registry_path(values: Mapping[str, str]) -> Path:
    state_home = values.get("XDG_STATE_HOME")
    if state_home:
        base = Path(state_home).expanduser()
    else:
        base = Path(values.get("HOME", str(Path.home()))).expanduser() / ".local" / "state"
    return base / "aiflow" / "checkout-registry.json"


def new_run_id() -> str:
    return str(uuid.uuid4())


def runtime_path(
    context: ProjectContext, run_id: str, *, env: Mapping[str, str] | None = None
) -> Path:
    values = os.environ if env is None else env
    base = values.get("XDG_RUNTIME_DIR")
    root = Path(base) if base else Path(f"/tmp/aiflow-{os.getuid()}")
    return root / "aiflow" / context.checkout_id / run_id


def cache_path(
    context: ProjectContext, *, env: Mapping[str, str] | None = None
) -> Path:
    values = os.environ if env is None else env
    base = values.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path(values.get("HOME", str(Path.home()))) / ".cache"
    return root / "aiflow" / context.checkout_id


class CheckoutRegistry:
    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> dict[str, str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise IdentityError(f"invalid checkout registry {self.path}: {exc}") from exc
        return {str(key): str(value) for key, value in payload.items()}

    def register(self, checkout_id: str, git_common_dir: Path) -> None:
        location = str(git_common_dir.resolve())
        records = self._load()
        previous = records.get(checkout_id)
        if previous and Path(previous).resolve() != Path(location) and Path(previous).exists():
            raise IdentityCollision(
                f"checkout ID {checkout_id} is registered at both {previous} and {location}"
            )
        records[checkout_id] = location
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".registry.", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(records, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def validate_thread_identity(
    record: Mapping[str, object], *, checkout_id: str, run_id: str,
    cwd: Path, worktree_id: str,
) -> None:
    expected = {
        "checkout_id": checkout_id,
        "run_id": run_id,
        "expected_cwd": str(cwd.resolve()),
        "worktree_id": worktree_id,
    }
    mismatches = [
        f"{key}: recorded={record.get(key)!r} expected={value!r}"
        for key, value in expected.items() if str(record.get(key, "")) != value
    ]
    if mismatches:
        raise ThreadIdentityMismatch("thread identity mismatch: " + "; ".join(mismatches))
