# AIFLOW v2 build state

## Current checkpoint

- Phase: `P6-P8`
- State: `P5_ACCEPTED_LOCALLY`
- Branch: `codex/aiflow-v2-lightweight-multiproject`
- Base: `e9311a932dc2d5bab57c2cfd7ed734b8e1ca5466`
- Active acceptance target: quality/deprecation migration, finite Solo/orchestrated
  execution, native custom agents, schema repair, and two-phase Git integration
- Acceptance IDs closed: `AC-PERM-001`, `AC-BACKEND-001`, `AC-ID-001`, `AC-ID-002`,
  `AC-ID-003`, `AC-ID-004`, `AC-STATE-001`, `AC-INSTALL-001`, `AC-SKILL-001`,
  `AC-PROGRESS-001`, `AC-PROGRESS-002`, `AC-PROGRESS-003`
- Next action: write functional quality, controller, custom-agent, migration, and
  integration tests before replacing the remaining legacy implementations.

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
- consecutive accepted checkpoints without acceptance delta: 0 (P5 closed three IDs)
- environment corrections: 0

## Safe resume

```text
git switch codex/aiflow-v2-lightweight-multiproject
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Read this file, `ACCEPTANCE.md`, and the tail of `BUILD_PROGRESS.jsonl` before resuming.
