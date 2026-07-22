from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipapp
import zipfile
from pathlib import Path
from typing import Any

from aiflow import __version__


FORBIDDEN_PARTS = {".git", ".worktrees", "node_modules", "backups", "runtime", "cache"}
REQUIRED = {
    "__main__.py",
    "aiflow/__init__.py",
    "aiflow/api/static/index.html",
    ".agents/skills/tdd-solo/SKILL.md",
}
BOOTSTRAP = '''from __future__ import annotations
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
'''


def _digest(path: Path) -> str:
    block = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            block.update(chunk)
    return block.hexdigest()


def _ignored(_: str, names: list[str]) -> set[str]:
    return {name for name in names if name == "__pycache__" or name.endswith((".pyc", ".pyo"))}


def _stage(distribution_root: Path, stage: Path) -> dict[str, str]:
    shutil.copytree(distribution_root / "src" / "aiflow", stage / "aiflow", ignore=_ignored)
    shutil.copytree(distribution_root / ".agents", stage / ".agents", ignore=_ignored)
    codex = distribution_root / ".codex"
    if codex.is_dir():
        shutil.copytree(codex, stage / ".codex", ignore=_ignored)
    (stage / "__main__.py").write_text(BOOTSTRAP, encoding="utf-8")
    files = sorted(path for path in stage.rglob("*") if path.is_file())
    manifest = {
        path.relative_to(stage).as_posix(): _digest(path)
        for path in files
    }
    (stage / "ARTIFACT_MANIFEST.json").write_text(
        json.dumps(
            {"schema_version": 1, "workflow_version": __version__, "files": manifest},
            indent=2,
            sort_keys=True,
        ) + "\n",
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
            {"schema_version": 1, "artifact": artifact.name, "sha256": checksum, "files": manifest},
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    verified = verify_artifact(artifact)
    if not verified["ok"]:
        raise ValueError("built artifact failed verification: " + "; ".join(verified["errors"]))
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
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("ARTIFACT_MANIFEST.json"))["files"]
            for name, digest in manifest.items():
                if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                    errors.append(f"payload checksum mismatch: {name}")
            for name in names:
                if FORBIDDEN_PARTS.intersection(Path(name).parts):
                    errors.append(f"forbidden archive path: {name}")
    except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        errors.append(f"invalid zipapp: {exc}")
        names = set()
    missing = sorted(REQUIRED - names)
    if missing:
        errors.append("missing required payload: " + ", ".join(missing))
    return {"ok": not errors, "errors": errors, "sha256": actual, "files": len(names)}
