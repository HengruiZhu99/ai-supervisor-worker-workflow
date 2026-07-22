# AIFLOW v2 build state

## Current checkpoint

- Phase: `RED`
- State: `REQUIRED_REGRESSIONS_FAILING_AS_INTENDED`
- Branch: `codex/aiflow-v2-lightweight-multiproject`
- Base: `e9311a932dc2d5bab57c2cfd7ed734b8e1ca5466`
- Active acceptance target: P1 permission safety, Codex/GPT-5.6 role defaults, and
  generic project resolution for `AC-PERM-001`, `AC-BACKEND-001`, `AC-BACKEND-002`,
  `AC-ID-002`, and `AC-QUALITY-002`
- Acceptance IDs closed: none (P0 is the permitted baseline phase)
- Next action: make only the P1 permission/backend/resolution/contamination tests green,
  rerun the legacy suite, and record the first implementation acceptance closure.

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

- unchanged failing command repeats: 1 (deliberate complete RED suite; no repeat before code changes)
- same normalized implementation failure: 0
- consecutive accepted checkpoints without acceptance delta: 0
- environment corrections: 0

## Safe resume

```text
git switch codex/aiflow-v2-lightweight-multiproject
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Read this file, `ACCEPTANCE.md`, and the tail of `BUILD_PROGRESS.jsonl` before resuming.
