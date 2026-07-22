from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


class SeedImportError(RuntimeError):
    """The authoritative skill seed is missing, corrupt, or unsafe."""


EXPECTED_SKILLS = ("grill-me-nr", "handoff-nr", "tdd-nr")


def _validate_member(info: zipfile.ZipInfo, seen: set[str]) -> PurePosixPath:
    name = info.filename
    path = PurePosixPath(name)
    if not name or name in seen:
        raise SeedImportError(f"duplicate or empty ZIP member: {name!r}")
    seen.add(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise SeedImportError(f"unsafe ZIP path: {name!r}")
    mode = info.external_attr >> 16
    kind = stat.S_IFMT(mode)
    if kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise SeedImportError(f"links/devices are forbidden in skill seed: {name!r}")
    return path


def import_seed(
    archive: Path,
    target: Path,
    *,
    expected_sha256: str,
) -> tuple[str, ...]:
    try:
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    except OSError as exc:
        raise SeedImportError(f"cannot read skill seed {archive}: {exc}") from exc
    if digest != expected_sha256:
        raise SeedImportError(f"skill seed checksum mismatch: {digest}")
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aiflow-seed-") as temporary:
        staging = Path(temporary)
        seen: set[str] = set()
        try:
            handle = zipfile.ZipFile(archive)
        except (OSError, zipfile.BadZipFile) as exc:
            raise SeedImportError(f"invalid skill seed: {exc}") from exc
        with handle:
            members = [(info, _validate_member(info, seen)) for info in handle.infolist()]
            for info, relative in members:
                destination = staging.joinpath(*relative.parts)
                if not destination.resolve().is_relative_to(staging.resolve()):
                    raise SeedImportError(f"ZIP member escapes staging: {info.filename!r}")
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with handle.open(info) as source, destination.open("xb") as output:
                    shutil.copyfileobj(source, output)
                os.chmod(destination, (info.external_attr >> 16) & 0o777 or 0o644)
        source_root = staging / "nr-design-tdd" / "skills"
        for name in EXPECTED_SKILLS:
            source = source_root / name
            if not (source / "SKILL.md").is_file():
                raise SeedImportError(f"required seed skill is absent: {name}")
            destination = target / name
            if destination.exists():
                raise SeedImportError(f"skill import conflict: {destination}")
            shutil.copytree(source, destination)
    return EXPECTED_SKILLS
