# GOAL.md template

This file is the durable implementation contract consumed by `/goal`. Keep it direct, executable, scenario-centered, and finite.

```markdown
# Goal: <feature or change>

- **Status:** READY_FOR_GOAL | READY_FOR_GOAL_WITH_ASSUMPTIONS
- **Source design:** `DESIGN.md`, revision <n>
- **Source test plan:** `TDD_PLAN.md`
- **State directory:** `<tracked repository-relative path>`

## Objective

<One objective.>

## Authoritative scenario

<The scientist-, user-, operator-, or downstream-consumer-visible scenario that must become true.>

**Authority:** <the live system, executable test, artifact, dataset, or independent reference that decides whether the scenario is true>.

## Success condition

<One binary success condition requiring every mandatory gate plus an independent final audit.>

## Read first

1. `AGENTS.md` and any more specific applicable instruction files
2. `DESIGN.md`
3. `TDD_PLAN.md`
4. `<state-directory>/IMPLEMENTATION_STATE.md`
5. the tail of `<state-directory>/PROGRESS.jsonl`
6. <named source files/tests/docs>

Do not begin implementation until the contract fingerprints and live repository state have been checked.

## Contract lock

At run initialization, record content fingerprints for:

- `DESIGN.md`
- `TDD_PLAN.md`
- `GOAL.md`

Store them in `IMPLEMENTATION_STATE.md`. A mismatch after initialization pauses execution unless an explicit `contract_change_authorized` event explains it. Do not silently adopt a modified contract.

## Scope

### Required

- ...

### Non-goals

- ...

## Accepted constraints and assumptions

- ...

## Repository and environment contract

- **Repository identity:** ...
- **Starting branch/commit:** ...
- **Authorized write locations:** ...
- **Required toolchain/platform:** ...
- **Required CPU/GPU/MPI resources:** ...
- **Minimum memory and disk:** ...
- **Dataset/checkpoint requirements:** ...
- **Approved alternate environment:** ...
- **Prohibited actions:** push/merge/destructive reset/etc. unless explicitly authorized

## Immutable contract gates

| ID | Requirement | Command/procedure | Pass condition | Evidence artifact | Re-verify handle |
|---|---|---|---|---|---|
| CT1 | R1 | `...` | ... | `<state-directory>/evidence/...` | `...` |

These gates may be strengthened but not weakened, skipped, shortened, or reinterpreted merely to obtain a pass.

## Cheap-to-expensive validation ladder

Run applicable levels in order and stop at the first failure:

1. **Static/configuration:** `...`
2. **Tiny deterministic probe:** `...`
3. **Negative/resource preflight:** `...`
4. **Focused smoke/component:** `...`
5. **Milestone regression:** `...`
6. **Expensive/full validation:** `...`

For every command in levels 5–6, record prerequisites, resource minimums, expected runtime class, evidence path, and an alternate route. Do not repeat an expensive failure without a material new hypothesis or changed resource state.

## Ordered scenario-centric milestones

### M1 — <observable slice>

- **Scenario delta:** <what becomes observably true when this milestone passes>
- **Depends on:** none
- **Contract:** R1, CT1
- **State path:** PENDING -> RED_ESTABLISHED -> IMPLEMENTING -> FOCUSED_GREEN -> AUDIT_PENDING -> PASSED

1. **Red/falsification:** run `...`; expected failure signature: ...
2. **Builder:** implement the smallest coherent change for the stated hypothesis.
3. **Focused green:** run `...`; pass condition: ...
4. **Simplifier:** perform at most one bounded cleanup pass that removes unnecessary structure while focused gates stay green.
5. **Independent auditor:** from a fresh or explicitly independent context, rerun `...`, inspect `<artifact>`, and record `audit_result` in `PROGRESS.jsonl`.
6. **Regression:** run `...`.
7. **Evidence:** retain ...
8. **Exit:** advance only when the focused gate, audit, and regression all pass.

<Repeat in dependency order. Do not organize milestones only by repository or file.>

## Role separation

- **Builder:** owns production writes and one active hypothesis.
- **Simplifier:** acts only after focused green; removes unnecessary indirection without changing the contract.
- **Auditor:** does not trust builder summaries, does not modify the implementation under review, reruns exact commands, and inspects retained artifacts.
- Use subagents primarily for bounded read-heavy exploration, test analysis, simplification review, and auditing. Do not let parallel agents write the same files.

## Durable state protocol

The state directory contains:

- `IMPLEMENTATION_STATE.md` — compact current snapshot;
- `PROGRESS.jsonl` — append-only checkpoint history;
- `evidence/` — retained validation artifacts;
- `repo-state.json` — repository and contract fingerprint snapshot;
- `HANDOFF.md` and `RESUME_PROMPT.md` — created only for a session/host transition.

### Snapshot rules

After every meaningful checkpoint:

1. increment the checkpoint number;
2. record one active milestone, one hypothesis, one bounded next action, and its exact verification handle;
3. update normalized failure, retry, no-progress, and environment-correction counters;
4. classify load-bearing claims as `VERIFIED_CURRENT`, `VERIFIED_AT_CHECKPOINT`, `UNVERIFIED`, or `STALE`;
5. attach a re-verification command to every claim needed for future action;
6. write `IMPLEMENTATION_STATE.md` through a temporary file and atomic replace;
7. append one event to `PROGRESS.jsonl`;
8. never rewrite prior ledger entries to hide failure.

The snapshot is an index, not an oracle. After compaction, handoff, external changes, or a meaningful delay, re-run the named handle before acting on a stored claim.

### Progress definition

A checkpoint counts as meaningful progress only when at least one is true:

- a mandatory gate changes state;
- a measured error, constraint, score, or runtime moves in the required direction;
- a failure signature is narrowed to a new falsifiable root-cause hypothesis;
- a milestone state advances;
- a blocker is proven external and an approved alternate route is selected.

“Read more files”, “tried again”, or “changed code” alone does not reset the no-progress counter.

## Progress ledger event

Each event must record:

- milestone and state transition;
- role;
- hypothesis and bounded action;
- exact commands and outcomes;
- changed files;
- gate delta or measured progress;
- normalized failure signature and counters;
- Git HEAD;
- evidence paths;
- one next action and re-verification handle.

## Change control

- Follow `DESIGN.md`; do not silently change scientific conventions, APIs, formats, architecture, or acceptance criteria.
- Do not weaken contract tests or thresholds.
- Correct an objectively defective contract gate only with recorded evidence. Pause for user input before any weakening of the accepted contract.
- Keep unrelated cleanup and dependency upgrades out of scope.
- Treat donor branches, archival results, old logs, and prior summaries as non-authoritative unless re-verified.

## Loop, retry, and stop-loss guards

1. One active milestone and one falsifiable hypothesis at a time.
2. Establish red/falsification evidence before production changes.
3. Make one focused change, then run the cheapest relevant gate.
4. Do not rerun the same failing command more than twice without a material change to code, configuration, input, resources, or diagnostic hypothesis.
5. After three implementation attempts with the same normalized failure signature, perform root-cause diagnosis. If it yields no new testable hypothesis, pause as blocked.
6. If two consecutive checkpoints make no measurable progress on a mandatory gate, pause as blocked.
7. Before expensive work, pass the static, tiny, negative, and resource preflights. Refuse to repeat an expensive path without new evidence.
8. For dependency, permission, hardware, dataset, or environment failures, make at most one safe corrective attempt; then use an approved alternate route or pause.
9. Never delete, skip, quarantine, reduce precision, widen tolerance, reduce duration/resolution, or narrow coverage merely to pass.
10. Do not act on an `UNVERIFIED` or `STALE` stored claim before dereferencing its handle.
11. A milestone cannot close on builder evidence alone. It requires a simplification check and independent audit.
12. Do not expand into unrelated cleanup, architecture migration, dependency upgrades, or speculative optimization.
13. Ask the user only for an irreversible/high-impact decision, direct contract conflict, or safety/security boundary; group no more than three questions and include recommended defaults.
14. Do not create recursive handoffs or repeatedly summarize the same state.

## Handoff protocol

Create a handoff only:

- at a recoverable milestone boundary;
- before moving to a fresh session or host;
- when the user explicitly asks;
- when continued context degradation risks losing the active hypothesis or state.

Before handoff:

1. stop new implementation work;
2. run only cheap load-bearing checks;
3. update the durable state and ledger;
4. preserve all dirty work by exact path, patch, or authorized checkpoint commit;
5. invoke `$handoff-nr Create a verified handoff for the active Goal run.`

A fresh session must use `$handoff-nr Resume from <state-directory>/HANDOFF.md.` before restarting `/goal`. It should continue without ceremonial confirmation when the resume gate matches.

## Final validation

Run in this order:

1. all immutable contract gates from a clean or explicitly characterized state;
2. broader regressions;
3. scenario-level artifact or downstream-consumer validation;
4. independent final audit that reruns exact commands and inspects retained artifacts;
5. documentation and state consistency checks.

Retain: <logs, metrics, plots, output files, benchmark records, auditor report, and final repository-state snapshot>.

## Stop conditions

### Success

Stop successfully only when:

- every immutable contract gate passes;
- every mandatory requirement in `TDD_PLAN.md` has passing evidence;
- the final broader regression sequence passes, except explicitly recorded unrelated baseline failures;
- the authoritative scenario is true in the named system or artifact;
- an independent final audit agrees;
- documentation, `IMPLEMENTATION_STATE.md`, and retained evidence match the implementation;
- a `run_completed` event is appended.

### Handoff

Pause for handoff when the handoff trigger fires and a recoverable checkpoint exists. Do not label a handoff as success or blocker.

### Blocked

Pause and report a blocker when:

- the retry, no-progress, or expensive-command guard fires;
- required evidence cannot be produced in the available or approved alternate environment;
- a material design, contract, or acceptance conflict appears;
- a required user decision is irreversible or high impact;
- repository state cannot be recovered safely.

A blocker report must include the exact command, normalized failure signature, attempts made, files changed, current branch and SHA, state/evidence paths, current safe state, smallest missing decision or resource, and resume point.
```
