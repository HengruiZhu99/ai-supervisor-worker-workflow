from __future__ import annotations

import hashlib
import json
import shutil
import stat
import tempfile
import zipapp
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from aiflow import __version__
from aiflow.security.scan import PATTERNS


FORBIDDEN_PARTS = {".git", ".worktrees", "node_modules", "backups", "runtime", "cache"}
REQUIRED = {
    "__main__.py",
    "aiflow/__init__.py",
    "aiflow/api/static/index.html",
    ".agents/skills/tdd-solo/SKILL.md",
}
FORBIDDEN_STATE_NAMES = {
    "RUN.json",
    "TASKS.json",
    "EVENTS.jsonl",
    "TRANSACTION.json",
    "CONTROLLER_LEASE.json",
    "MUTATING_RUN.json",
    "project.lock",
}
BOOTSTRAP = """from __future__ import annotations
import sys
import tempfile
import zipfile
from pathlib import Path

archive = Path(sys.argv[0]).resolve()
with tempfile.TemporaryDirectory(prefix="aiflow-artifact-") as temporary:
    root = Path(temporary).resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            if member.filename.startswith((".agents/", ".codex/")):
                target = (root / member.filename).resolve()
                if root not in target.parents:
                    raise SystemExit("unsafe packaged asset path")
                bundle.extract(member, root)
    import aiflow.cli.main as cli
    cli.DISTRIBUTION_ROOT_OVERRIDE = root
    raise SystemExit(cli.main())
"""


def _digest(path: Path) -> str:
    block = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            block.update(chunk)
    return block.hexdigest()


def _ignored(_: str, names: list[str]) -> set[str]:
    return {
        name
        for name in names
        if name == "__pycache__" or name.endswith((".pyc", ".pyo"))
    }


def _validate_source_tree(root: Path) -> None:
    for relative in (Path("src/aiflow"), Path(".agents"), Path(".codex")):
        source = root / relative
        if not source.exists():
            if relative == Path(".codex"):
                continue
            raise ValueError(f"missing artifact source tree: {relative}")
        for path in (source, *source.rglob("*")):
            if path.is_symlink():
                raise ValueError(
                    f"artifact source contains symlink: {path.relative_to(root)}"
                )
            if path.exists() and not (path.is_file() or path.is_dir()):
                raise ValueError(
                    f"artifact source contains special file: {path.relative_to(root)}"
                )


def _stage(distribution_root: Path, stage: Path) -> dict[str, str]:
    _validate_source_tree(distribution_root)
    shutil.copytree(
        distribution_root / "src" / "aiflow", stage / "aiflow", ignore=_ignored
    )
    shutil.copytree(distribution_root / ".agents", stage / ".agents", ignore=_ignored)
    codex = distribution_root / ".codex"
    if codex.is_dir():
        shutil.copytree(codex, stage / ".codex", ignore=_ignored)
    (stage / "__main__.py").write_text(BOOTSTRAP, encoding="utf-8")
    files = sorted(path for path in stage.rglob("*") if path.is_file())
    manifest = {path.relative_to(stage).as_posix(): _digest(path) for path in files}
    (stage / "ARTIFACT_MANIFEST.json").write_text(
        json.dumps(
            {"schema_version": 1, "workflow_version": __version__, "files": manifest},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def build_artifact(distribution_root: Path, destination: Path) -> dict[str, Any]:
    root = distribution_root.resolve()
    output = destination.resolve()
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / f"aiflow-{__version__}.pyz"
    with tempfile.TemporaryDirectory(prefix="aiflow-package-") as temporary:
        stage = Path(temporary) / "stage"
        stage.mkdir()
        manifest = _stage(root, stage)
        zipapp.create_archive(
            stage,
            target=artifact,
            interpreter="/usr/bin/env python3",
            compressed=True,
        )
    artifact.chmod(0o755)
    checksum = _digest(artifact)
    checksum_file = artifact.with_suffix(artifact.suffix + ".sha256")
    checksum_file.write_text(f"{checksum}  {artifact.name}\n", encoding="utf-8")
    manifest_file = artifact.with_suffix(artifact.suffix + ".manifest.json")
    manifest_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifact": artifact.name,
                "sha256": checksum,
                "files": manifest,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    verified = verify_artifact(artifact)
    if not verified["ok"]:
        raise ValueError(
            "built artifact failed verification: " + "; ".join(verified["errors"])
        )
    return {
        "artifact": str(artifact),
        "checksum_file": str(checksum_file),
        "manifest_file": str(manifest_file),
        "sha256": checksum,
        "files": len(manifest),
    }


def verify_artifact(artifact: Path) -> dict[str, Any]:
    errors: list[str] = []
    path = artifact.resolve()
    sidecar = path.with_suffix(path.suffix + ".sha256")
    try:
        expected = sidecar.read_text(encoding="utf-8").split()[0]
    except (FileNotFoundError, IndexError, OSError):
        expected = ""
        errors.append("missing or invalid checksum sidecar")
    actual = _digest(path) if path.is_file() else ""
    if expected and actual != expected:
        errors.append("artifact checksum mismatch")
    archive_errors, names, manifest = _inspect_archive(path)
    errors.extend(archive_errors)
    missing = sorted(REQUIRED - names)
    if missing:
        errors.append("missing required payload: " + ", ".join(missing))
    errors.extend(_external_manifest_errors(path, actual, manifest))
    return {
        "ok": not errors,
        "errors": sorted(set(errors)),
        "sha256": actual,
        "files": len(names),
    }


def _inspect_archive(path: Path) -> tuple[list[str], set[str], dict[str, str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            return _inspect_open_archive(archive)
    except (
        OSError,
        KeyError,
        ValueError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
    ) as exc:
        return [f"invalid zipapp: {exc}"], set(), {}


def _inspect_open_archive(
    archive: zipfile.ZipFile,
) -> tuple[list[str], set[str], dict[str, str]]:
    errors: list[str] = []
    infos = archive.infolist()
    listed = [info.filename for info in infos]
    names = set(listed)
    if len(listed) != len(names):
        errors.append("archive contains duplicate member names")
    for info in infos:
        errors.extend(_member_errors(info))
    internal = json.loads(archive.read("ARTIFACT_MANIFEST.json"))
    manifest = internal["files"]
    if not isinstance(manifest, dict):
        raise ValueError("internal artifact manifest files must be an object")
    files = {info.filename for info in infos if not info.is_dir()}
    errors.extend(_manifest_set_errors(files, set(manifest)))
    for name, digest in manifest.items():
        if name in files and hashlib.sha256(archive.read(name)).hexdigest() != digest:
            errors.append(f"payload checksum mismatch: {name}")
        if name in files:
            errors.extend(_payload_errors(name, archive.read(name)))
    return errors, names, {str(key): str(value) for key, value in manifest.items()}


def _manifest_set_errors(files: set[str], declared: set[str]) -> list[str]:
    extras = sorted(files - declared - {"ARTIFACT_MANIFEST.json"})
    missing = sorted(declared - files)
    return [
        *(f"unmanifested archive file: {name}" for name in extras),
        *(f"manifested file missing from archive: {name}" for name in missing),
    ]


def _member_errors(info: zipfile.ZipInfo) -> list[str]:
    name = info.filename
    path = PurePosixPath(name)
    errors: list[str] = []
    unsafe = (
        not name
        or "\\" in name
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    )
    if unsafe:
        errors.append(f"unsafe archive path: {name}")
    if FORBIDDEN_PARTS.intersection(path.parts):
        errors.append(f"forbidden archive path: {name}")
    mode = (info.external_attr >> 16) & 0o170000
    if mode and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        errors.append(f"unsafe archive special member: {name}")
    return errors


def _payload_errors(name: str, content: bytes) -> list[str]:
    errors: list[str] = []
    if PurePosixPath(name).name in FORBIDDEN_STATE_NAMES:
        errors.append(f"forbidden state file in artifact: {name}")
    if b"\x00" not in content and len(content) <= 1_000_000:
        text = content.decode("utf-8", errors="replace")
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                errors.append(f"secret pattern {label} in artifact member: {name}")
    return errors


def _external_manifest_errors(
    path: Path, checksum: str, manifest: dict[str, str]
) -> list[str]:
    external_path = path.with_suffix(path.suffix + ".manifest.json")
    try:
        external = json.loads(external_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"missing or invalid external manifest: {exc}"]
    errors: list[str] = []
    if external.get("artifact") != path.name:
        errors.append("external manifest artifact name mismatch")
    if external.get("sha256") != checksum:
        errors.append("external manifest checksum mismatch")
    if external.get("files") != manifest:
        errors.append("external and internal payload manifests differ")
    return errors
