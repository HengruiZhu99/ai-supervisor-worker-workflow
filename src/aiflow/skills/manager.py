from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Mapping


class SkillValidationError(RuntimeError):
    """A skill is invalid or differs from its lock."""


class SkillCollision(SkillValidationError):
    """The same skill name is visible from more than one scope."""


FRONTMATTER = re.compile(r"\A---\n(.*?)\n---(?:\n|\Z)", re.DOTALL)
NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(file_hash(path).encode())
        digest.update(b"\0")
    return digest.hexdigest()


def metadata(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SkillValidationError(f"cannot read {path}: {exc}") from exc
    match = FRONTMATTER.match(text)
    if not match:
        raise SkillValidationError(f"missing YAML frontmatter: {path}")
    result: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator:
            result[key.strip()] = value.strip().strip('"').strip("'")
    if set(result) != {"name", "description"}:
        raise SkillValidationError(f"frontmatter must contain only name and description: {path}")
    if not NAME.fullmatch(result["name"]) or not result["description"]:
        raise SkillValidationError(f"invalid skill name or empty description: {path}")
    return result


class SkillManager:
    def __init__(
        self,
        *,
        repository: Path,
        user: Path | None = None,
        admin: Path | None = None,
        system: Path | None = None,
    ) -> None:
        self.scopes = {
            "repository": repository,
            "user": user,
            "admin": admin,
            "system/plugin": system,
        }

    @staticmethod
    def _skill_dirs(root: Path | None, *, recursive: bool = False) -> list[Path]:
        if root is None or not root.is_dir():
            return []
        if recursive:
            return sorted({path.parent for path in root.rglob("SKILL.md")})
        return sorted(
            path for path in root.iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        )

    def list(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for scope, root in self.scopes.items():
            for directory in self._skill_dirs(root, recursive=scope == "system/plugin"):
                info = metadata(directory / "SKILL.md")
                rows.append({
                    "scope": scope,
                    "name": info["name"],
                    "description": info["description"],
                    "path": str(directory),
                    "hash": tree_hash(directory),
                })
        return rows

    def validate(self) -> dict[str, str]:
        hashes: dict[str, str] = {}
        repository = self.scopes["repository"]
        for directory in self._skill_dirs(repository):
            info = metadata(directory / "SKILL.md")
            if info["name"] != directory.name:
                raise SkillValidationError(
                    f"skill folder/name mismatch: {directory.name!r} != {info['name']!r}"
                )
            for path in directory.rglob("*"):
                if path.is_symlink():
                    raise SkillValidationError(f"repository skill contains a symlink: {path}")
            hashes[info["name"]] = tree_hash(directory)
        return hashes

    def doctor(self) -> dict[str, object]:
        rows = self.list()
        by_name: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            by_name.setdefault(row["name"], []).append(row)
        collisions = {name: entries for name, entries in by_name.items() if len(entries) > 1}
        if collisions:
            detail = "; ".join(
                f"{name}: {', '.join(row['scope'] for row in entries)}"
                for name, entries in sorted(collisions.items())
            )
            raise SkillCollision(f"duplicate skill names require explicit resolution: {detail}")
        return {"ok": True, "skills": rows, "collisions": {}}

    def sync(self, source: Path, *, expected_hashes: Mapping[str, str]) -> dict[str, str]:
        repository = self.scopes["repository"]
        assert repository is not None
        current = self.validate()
        for name, expected in expected_hashes.items():
            if current.get(name) != expected:
                raise SkillValidationError(f"refusing to overwrite drifted skill: {name}")
        repository.mkdir(parents=True, exist_ok=True)
        updated: dict[str, str] = {}
        for source_dir in self._skill_dirs(source):
            name = metadata(source_dir / "SKILL.md")["name"]
            destination = repository / name
            with tempfile.TemporaryDirectory(prefix="aiflow-skill-sync-") as temporary:
                staged = Path(temporary) / name
                shutil.copytree(source_dir, staged)
                if destination.exists():
                    shutil.rmtree(destination)
                os.replace(staged, destination)
            updated[name] = tree_hash(destination)
        return updated
