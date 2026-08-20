from __future__ import annotations

import hashlib
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiflow.skills.manager import SkillCollision, SkillManager, SkillValidationError  # noqa: E402
from aiflow.skills.seed import SeedImportError, import_seed  # noqa: E402


SEED_SKILLS = ("grill-me-nr", "handoff-nr", "tdd-nr")


def make_seed_archive(path: Path) -> str:
    with zipfile.ZipFile(path, "w") as handle:
        for name in SEED_SKILLS:
            source = ROOT / ".agents" / "skills" / name
            for item in sorted(source.rglob("*")):
                if item.is_file():
                    member = (
                        Path("nr-design-tdd/skills") / name / item.relative_to(source)
                    )
                    handle.write(item, member.as_posix())
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SkillManagementTests(unittest.TestCase):
    def test_authoritative_seed_imports_three_named_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "seed.zip"
            target = root / ".agents" / "skills"
            imported = import_seed(
                archive, target, expected_sha256=make_seed_archive(archive)
            )
            self.assertEqual(imported, SEED_SKILLS)
            self.assertTrue(
                (target / "tdd-nr" / "references" / "GOAL_TEMPLATE.md").is_file()
            )
            self.assertTrue(
                (target / "handoff-nr" / "scripts" / "state_probe.py").is_file()
            )

    def test_seed_rejects_traversal_and_symlink_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("../escape", "bad")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with self.assertRaises(SeedImportError):
                import_seed(archive, Path(tmp) / "out", expected_sha256=digest)

            link_archive = Path(tmp) / "link.zip"
            with zipfile.ZipFile(link_archive, "w") as handle:
                info = zipfile.ZipInfo("nr-design-tdd/skills/tdd-nr/link")
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                handle.writestr(info, "../../outside")
            digest = hashlib.sha256(link_archive.read_bytes()).hexdigest()
            with self.assertRaises(SeedImportError):
                import_seed(link_archive, Path(tmp) / "out2", expected_sha256=digest)

    def test_validate_requires_matching_folder_frontmatter_and_safe_resources(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills"
            skill = root / "example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: wrong\ndescription: useful\n---\n\n# Example\n",
                encoding="utf-8",
            )
            with self.assertRaises(SkillValidationError):
                SkillManager(repository=root).validate()

    def test_repository_scope_collision_is_reported_not_silently_selected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repository = base / "repo"
            user = base / "user"
            for root in (repository, user):
                skill = root / "same-name"
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text(
                    "---\nname: same-name\ndescription: useful duplicate\n---\n\n# Same\n",
                    encoding="utf-8",
                )
            manager = SkillManager(repository=repository, user=user)
            with self.assertRaises(SkillCollision):
                manager.doctor()

    def test_sync_detects_hash_drift_before_replacing_vendored_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            target = base / "target"
            source_skill = source / "example"
            target_skill = target / "example"
            source_skill.mkdir(parents=True)
            target_skill.mkdir(parents=True)
            body = "---\nname: example\ndescription: useful skill\n---\n\n# Example\n"
            (source_skill / "SKILL.md").write_text(body, encoding="utf-8")
            (target_skill / "SKILL.md").write_text(
                body + "user edit\n", encoding="utf-8"
            )
            manager = SkillManager(repository=target)
            with self.assertRaises(SkillValidationError):
                manager.sync(
                    source, expected_hashes={"example": "not-the-current-hash"}
                )


if __name__ == "__main__":
    unittest.main()
