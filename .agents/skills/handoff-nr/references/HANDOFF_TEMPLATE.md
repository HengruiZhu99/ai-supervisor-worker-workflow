# HANDOFF.md template

This is a compact, evidence-backed continuation packet. It is not a transcript and it is not authoritative by itself. Every load-bearing claim must point to a command or artifact that can re-establish the current truth.

```markdown
# Handoff: <goal name>

- **Status:** HANDOFF_READY | HANDOFF_READY_WITH_UNVERIFIED_ITEMS | RESUME_BLOCKED_BY_STATE_DIVERGENCE | RESUME_BLOCKED_BY_ENVIRONMENT
- **Run ID:** <stable identifier from IMPLEMENTATION_STATE.md>
- **Checkpoint:** <monotonic integer>
- **Created:** <UTC timestamp>
- **State directory:** `<tracked repository-relative path>`

## Why this task exists

<One paragraph preserving the user's objective and the observable outcome that matters.>

## Contract pointers

| Artifact | Recorded fingerprint | Re-verify command |
|---|---|---|
| `DESIGN.md` | `<hash>` | `<exact command>` |
| `TDD_PLAN.md` | `<hash>` | `<exact command>` |
| `GOAL.md` | `<hash>` | `<exact command>` |

Do not continue if a contract fingerprint changed without an explicit contract-change record.

## Exact repository state

- **Repository identity:** <sanitized remote or other stable identifier>
- **Branch:** `<branch or detached>`
- **HEAD:** `<commit SHA>`
- **Upstream:** `<remote branch or none>`
- **Worktree:** clean | dirty
- **State probe:** `<path to repo-state.json>`
- **Re-verify:** `<state-probe command>`

### Dirty worktree, when applicable

| Path | State | Why it is intentionally uncommitted | Recovery or verification command |
|---|---|---|---|
| `...` | modified/untracked/etc. | ... | `...` |

Never describe uncommitted work only in prose. Preserve it in the workspace, a patch, or an authorized checkpoint commit and name the exact recovery path.

## Current milestone

- **Milestone:** `<ID — name>`
- **Milestone state:** PENDING | RED_ESTABLISHED | IMPLEMENTING | FOCUSED_GREEN | AUDIT_PENDING | PASSED | BLOCKED
- **Scenario being made true:** <consumer/scientist-visible vertical slice>
- **Current hypothesis:** <one falsifiable sentence>
- **Next action:** <one bounded action>
- **Next-action verification:** `<exact command or procedure>`
- **Do not repeat:** <failed action or hypothesis plus failure signature>

## Acceptance state

| Gate | Recorded state | Evidence | Re-verify command | Trust class |
|---|---|---|---|---|
| CT1 | pass/fail/not run | `<path>` | `...` | VERIFIED_AT_CHECKPOINT / UNVERIFIED / STALE |

The next session must re-run the handles for the active milestone and any claim it is about to rely on. The prose state is a pointer, not the source of truth.

## Progress since the previous checkpoint

- <Concrete gate delta, measured error reduction, or milestone transition.>
- <No generic “worked on” entries.>

## Failed approaches and stop-loss state

| Failure signature | Attempts | Evidence | Why another identical retry is forbidden | What would count as new evidence |
|---|---:|---|---|---|
| ... | ... | ... | ... | ... |

## Environment and resource requirements

- **Required platform/toolchain:** ...
- **Required CPU/GPU/MPI resources:** ...
- **Minimum memory/disk/runtime budget:** ...
- **Preflight command:** `...`
- **Observed capacity at checkpoint:** ...
- **Approved alternate environment:** ...

## Authoritative and non-authoritative artifacts

### Active sources of truth

- `<path, SHA, issue, dataset ID, or command>` — <role>

### Donor, archival, or stale material

- `<path or reference>` — <why it must not be treated as current>

## Open blockers and decisions

- None.

<Otherwise state the smallest blocking item, the evidence, and the exact resume condition.>

## Resume gate

The next task must:

1. read `AGENTS.md`, `DESIGN.md`, `TDD_PLAN.md`, `GOAL.md`, `IMPLEMENTATION_STATE.md`, and the tail of `PROGRESS.jsonl`;
2. run the repository-state verification command;
3. re-run the active milestone's load-bearing handles;
4. compare observed state with this handoff;
5. continue without asking for ceremonial confirmation when they match;
6. ask one compact batch only when a material mismatch cannot be safely reconciled.

## Goal restart prompt

`/goal <copy-paste objective that names GOAL.md, IMPLEMENTATION_STATE.md, and the exact active milestone; requires state refresh before action; and preserves all stop conditions>`
```
