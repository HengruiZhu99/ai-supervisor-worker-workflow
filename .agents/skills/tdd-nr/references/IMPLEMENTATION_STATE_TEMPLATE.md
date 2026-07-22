# IMPLEMENTATION_STATE.md template

This file is the compact current snapshot for a long Goal run. Keep it small enough to read at every checkpoint. Update it atomically; preserve history in `PROGRESS.jsonl`.

The snapshot is a pointer to live truth, not truth by itself. Any load-bearing claim must include a cheap re-verification handle.

```markdown
# Implementation state: <goal name>

- **Schema version:** 1
- **Run ID:** <stable identifier>
- **Status:** NOT_STARTED | RUNNING | PAUSED_FOR_HANDOFF | READY_TO_RESUME | BLOCKED | COMPLETE
- **Checkpoint:** <monotonic integer>
- **Updated:** <UTC timestamp>
- **State directory:** `<tracked repository-relative path>`

## Objective and authoritative scenario

- **Objective:** <one sentence copied from GOAL.md>
- **Scenario:** <consumer/scientist-visible behavior that must become true>
- **Success authority:** <tests, artifacts, or external system that decides truth>

## Contract lock

| Artifact | Fingerprint | Re-verify command |
|---|---|---|
| `DESIGN.md` | `<hash>` | `...` |
| `TDD_PLAN.md` | `<hash>` | `...` |
| `GOAL.md` | `<hash>` | `...` |

A mismatch pauses execution until an authorized contract change is recorded.

## Repository checkpoint

- **Repository identity:** <sanitized remote or stable local identifier>
- **Branch:** `<branch or detached>`
- **Base commit:** `<SHA>`
- **Current checkpoint commit:** `<SHA or none>`
- **Worktree:** clean | dirty
- **Repository-state snapshot:** `<state-dir>/repo-state.json`
- **Re-verify:** `<exact state-probe command>`

## Active milestone

- **ID:** M<n>
- **Name:** ...
- **State:** PENDING | RED_ESTABLISHED | IMPLEMENTING | FOCUSED_GREEN | AUDIT_PENDING | PASSED | BLOCKED
- **Requirements/gates:** R..., CT...
- **Current hypothesis:** <one falsifiable sentence>
- **One next action:** <one bounded action>
- **Next-action verification:** `<exact command/procedure>`
- **Expected result:** ...

## Forward-progress counters

- **Same failure signature attempts:** <n of 3>
- **Consecutive no-progress checkpoints:** <n of 2>
- **Environment corrections used:** <n of 1>
- **Expensive command retries without new evidence:** <n; must be 0>
- **Last failure signature:** <normalized signature or none>
- **What would count as new evidence:** <specific input/code/hypothesis/resource change>

## Milestone board

| Milestone | State | Contract gates | Last verified checkpoint | Re-verify handle |
|---|---|---|---:|---|
| M1 | ... | CT1 | ... | `...` |

## Truth ledger

| Claim needed for future action | Trust class | Evidence/address | Re-verification handle | Last checked |
|---|---|---|---|---|
| ... | VERIFIED_CURRENT / VERIFIED_AT_CHECKPOINT / UNVERIFIED / STALE | path/SHA/ID | `...` | timestamp |

Never act on `UNVERIFIED` or `STALE` prose. Dereference its handle first.

## Failed approaches and exclusions

| Failure signature | Attempts | Why it failed | Do not repeat until | Evidence |
|---|---:|---|---|---|
| ... | ... | ... | <new evidence condition> | ... |

## Environment and resource state

- **Required environment:** ...
- **Preflight command:** `...`
- **Last observed capacity:** ...
- **Approved alternate route:** ...

## Evidence index

| Gate/event | Artifact | Generating command | Fingerprint or key metric |
|---|---|---|---|
| CT1 | `<state-dir>/evidence/...` | `...` | ... |

## Blockers

- None.

<Otherwise record exact blocker, category, command/failure, owner, and resume condition.>
```

## Atomic update protocol

1. Read the current checkpoint number.
2. Write the complete next snapshot to a sibling temporary file.
3. Validate required fields and monotonic checkpoint number.
4. Use an atomic replace to install the temporary file.
5. Append the corresponding event to `PROGRESS.jsonl`.
6. Never edit prior JSONL events to hide a failure.
