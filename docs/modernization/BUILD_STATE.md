# AIFLOW v2 build state

## Current checkpoint

- Phase: `P12`
- State: `AIFLOW_V2_READY_WITH_OPTIONAL_LIMITATIONS`
- Branch: `codex/aiflow-v2-lightweight-multiproject`
- Base: `e9311a932dc2d5bab57c2cfd7ed734b8e1ca5466`
- Implementation freeze: `307169a8cb95f6907a3230bf36bc659706f1ba7d`
- Terminal artifact SHA-256: `3494ef74098733121c05d4cbbf01ec0686b6693869cec4b508944479c4fffd59`
- Acceptance target: closed; independent architecture and scientific/release audits
  accepted the exact implementation freeze with no unresolved critical/high finding
- Acceptance IDs closed: `AC-PERM-001`, `AC-BACKEND-001`, `AC-ID-001`, `AC-ID-002`,
  `AC-ID-003`, `AC-ID-004`, `AC-STATE-001`, `AC-INSTALL-001`, `AC-SKILL-001`,
  `AC-PROGRESS-001`, `AC-PROGRESS-002`, `AC-PROGRESS-003`, `AC-PERM-002`,
  `AC-BACKEND-002`, `AC-ID-005`, `AC-STATE-002`, `AC-SOLO-001`, `AC-SOLO-003`,
  `AC-AUTO-001`, `AC-EXEC-001`, `AC-EXEC-002`, `AC-QUALITY-001`, `AC-DEPR-001`,
  `AC-INTEGRATE-001`, `AC-STATE-003`, `AC-MIGRATE-001`, `AC-GUI-001`, `AC-GUI-002`,
  `AC-HPC-001`, `AC-HANDOFF-001`, `AC-SOLO-002`, `AC-QUALITY-002`, `AC-PACKAGE-001`,
  `AC-AUDIT-001`
- Next action: none for the accepted modernization. Optional owner decisions and finite
  compatibility removals are listed in `docs/OPTIONAL_LIMITATIONS.md`.

## Immutable inputs

- Accepted design: `aiflow-v2-lightweight-multiproject-kit/AIFLOW_V2_DESIGN.md`
- Grill decision: `aiflow-v2-lightweight-multiproject-kit/GRILL_REVIEW.md`
- Failure catalog: `aiflow-v2-lightweight-multiproject-kit/FAILURE_MODE_CATALOG.md`
- Execution contract: `aiflow-v2-lightweight-multiproject-kit/AIFLOW_V2_UPGRADE_PROMPT.md`
- Skill seed: `nr-design-tdd-v0.2.0.zip`, verified SHA-256 recorded in `BASELINE.md`

## User amendment

Codex becomes the default backend for all workflow roles. Cursor remains a compatibility
choice. Active defaults use current GPT-5.6 family tiers by role: Sol for hardest
controller/writer/reviewer work, Terra for balanced read-heavy/style/chat work, and Luna
for narrow high-volume classification/routing. Deterministic style gates use no model.

## Circuit-breaker counters

- unchanged failing command repeats: 0
- same normalized implementation failure: 0
- consecutive accepted checkpoints without acceptance delta: 0 (P11 closed three IDs)
- environment corrections: 0

## Terminal verification

```text
git switch codex/aiflow-v2-lightweight-multiproject
bin/aiflow project verify
bin/aiflow quality check --diff-base e9311a932dc2d5bab57c2cfd7ed734b8e1ca5466
bin/aiflow package verify dist/aiflow-0.4.0.dev0.pyz
```

Read `P12_TERMINAL_EVIDENCE.md`, `P12_AUDITS.md`, and
`docs/OPTIONAL_LIMITATIONS.md` before changing this terminal classification.
