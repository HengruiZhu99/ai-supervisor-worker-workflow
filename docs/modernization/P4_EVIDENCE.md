# P4 Evidence: Profiles, Canonical Skills, and Project Lifecycle

Date: 2026-07-22

## Implemented contract

- The canonical project contract is `.aiflow/project.toml`, `project.lock`,
  `quality.toml`, `deprecations.toml`, and `handoffs/`.
- Project lifecycle commands implement init, status, verify, upgrade, rollback, and
  uninstall. Vendoring is hash-locked, idempotent, backup-aware, transactional, and
  uninstall preserves modified managed files.
- All five profiles install only their explicit inherited skill set.
- The authoritative seed checksum is enforced before safe extraction. Absolute,
  traversal, duplicate, link, device, and conflicting members fail closed.
- `grill-me-nr`, `tdd-nr`, and `handoff-nr` were imported from the verified seed.
- `tdd-solo` and `aiflow-autonomous` were adapted into the canonical tree. Required
  profile skills and existing scientific review skills are also canonical there.
- `aiflow skills list|validate|doctor|sync` use `.agents/skills`; doctor detects
  repository, user, administrator, and nested system/plugin collisions.
- The source-tree `bin/aiflow` is now a thin package entry point and never trusts an
  inherited project selector.

## Skill inventory

The repository distribution contains 20 validated skills. The `full` profile vendors
18; the two legacy workflow-maintenance skills remain available to this distribution but
are not silently installed into target projects.

Authoritative seed skills:

```text
grill-me-nr
handoff-nr
tdd-nr
```

Primary execution skills:

```text
tdd-solo
aiflow-autonomous
```

## Fresh evidence

```text
python3 -m unittest tests.unit.test_skill_management \
  tests.unit.test_project_lifecycle tests.unit.test_cli_lifecycle
13 tests passed

python3 scripts/list_skills.py
20 canonical repository skills listed

bin/aiflow --project-root . project verify
ok=true, missing=[], modified=[]

bin/aiflow --project-root . skills validate
20 skills validated

temporary full-profile init + project verify
profile=full, ok=true
```

The upstream skill-creator validator could not run in this dependency-free environment
because it imports PyYAML. The product's standard-library validator covers required
frontmatter, folder/name consistency, safe resources, tree hashes, and collisions; all
20 pass. No dependency was added merely to run the helper.

## Acceptance delta

- Closed: `AC-INSTALL-001` for the default vendor/copy mode and all five profiles.
- Closed: `AC-SKILL-001`.
- Closed: the profile/current-path portion of `AC-SOLO-001` and `AC-AUTO-001`; execution
  behavior and custom agents remain open for later phases.
