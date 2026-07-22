---
name: aiflow-autonomous
description: Execute a decision-complete multi-milestone engineering goal through bounded direct-child Codex agents, acceptance-ID progress, one writer per worktree, one durable state writer, independent review, and verified handoffs. Use explicitly; prefer tdd-solo for one bounded task.
---

# AIFLOW Autonomous

## Purpose

Execute an accepted multi-milestone goal when delegation provides real value.

For one coherent feature, fix, refactor, test, numerical change, portability change, or
performance correction, use `$tdd-solo` instead.

This skill is orchestration policy. The deterministic `aiflow` engine owns identity,
state, leases, transitions, evidence, integration, and recovery.

## Preconditions

Read:

- applicable `AGENTS.md`;
- accepted `DESIGN.md`;
- `TDD_PLAN.md`;
- `GOAL.md`;
- current project lock and quality/deprecation policy;
- active run state when resuming;
- `references/STATE_PROTOCOL.md`;
- `references/SUBAGENT_RETURN_SCHEMA.md`.

Require:

- one objective and stopping condition;
- stable acceptance IDs;
- exact mandatory gates;
- bounded milestones;
- explicit non-goals;
- verified project/checkout identity.

If the task is actually one bounded objective, stop as
`AUTONOMOUS_RUN_SOLO_RECOMMENDED`.

Verify and start through the deterministic CLI:

```text
aiflow --project-root <repo> project verify
aiflow --project-root <repo> skills doctor
aiflow --project-root <repo> run start --mode orchestrated --parent-sandbox workspace-write --objective "<accepted goal>" --acceptance-id <AC-ID>
```

Resume with explicit finite budgets and the verified parent sandbox. Use `state verify`,
`quality check`, and the two-phase `integrate` command; never edit canonical snapshots or
apply a candidate directly to the target branch.

## Agent topology

The parent is sole controller, state writer, and integrator.

Use direct-child project agents only where useful:

- codebase mapper;
- documentation researcher;
- test architect;
- implementation worker;
- scientific reviewer;
- engineering reviewer;
- UI auditor;
- release auditor.

Every child custom-agent configuration disables subagent tools:

```toml
[agents]
enabled = false
```

Every child prompt also says:

```text
Do not launch or request subagents. Do not invoke aiflow-autonomous.
Return the required structured result and stop.
```

Before spawning, verify the parent permission mode. Do not delegate under an unrestricted
permission override that would invalidate read-only role guarantees.

Normal concurrency:

- up to three read-heavy children;
- one writer per worktree;
- one state writer;
- one integrator.

## Question budget

Normal: zero.

Hard maximum:

- one message;
- at most three questions;
- only for an irreducible contract, ownership, or destructive-action decision.

No routine approval questions.

## Progress model

Every goal has acceptance IDs.

Task value classes:

- `delivery`: directly closes acceptance IDs;
- `validation`: independently proves acceptance IDs;
- `enabler`: unblocks one named ready delivery/validation task;
- `housekeeping`: incidental non-goal maintenance;
- `research`: read-only evidence, never an implementation job.

Dispatch priority:

```text
delivery → validation → one named enabler → explicit-goal housekeeping
```

Accepting an enabler creates progress debt. No unrelated task may run until the named
target is dispatched, deferred, or the run blocks.

Two accepted checkpoints without an acceptance-ID delta trigger one replan and then a
no-progress blocker.

## Finite workflow

### Phase 0 — Verify or resume

1. Resolve project, checkout, worktree, and run identity.
2. Scrub inherited project context.
3. Verify contract and project-lock hashes.
4. Verify controller lease and state revision.
5. Verify Git state and active worktree ownership.
6. Re-run load-bearing handoff handles once.
7. Reconcile one unambiguous mechanical mismatch; otherwise block.

### Phase 1 — Select one milestone and ready task

- One active milestone.
- One active hypothesis per task.
- Dependencies accepted.
- Value class valid.
- Acceptance target named.
- File/symbol ownership bounded.
- Diff and resource budgets recorded.
- One next action.

Do not create a worker job for planning or open-ended research.

### Phase 2 — Gather bounded evidence

Parallelize only independent read-heavy work.

Each child receives a bounded context capsule containing:

- task objective;
- acceptance IDs;
- contract hashes;
- relevant files/symbols;
- non-goals;
- current hypothesis;
- exact commands;
- prior failure signatures;
- allowed scope;
- result schema;
- evidence directory.

Wait for all load-bearing results. Raw output remains in evidence.

### Phase 3 — Establish falsification

Before production changes, establish the applicable evidence-first baseline:

- failing feature/regression test;
- characterization test;
- analytic/manufactured/numerical criterion;
- performance correctness/baseline;
- browser reproduction;
- migration parity test.

Record why the evidence discriminates.

### Phase 4 — Dispatch one bounded writer

The writer:

- owns one task/worktree;
- edits only allowed scope;
- cannot change contracts;
- cannot merge, push, publish, or alter state;
- cannot launch children;
- implements the smallest coherent change;
- stores result/evidence in its inbox;
- stops.

Parallel writers require separate worktrees and disjoint ownership.

### Phase 5 — Ingest and verify

The controller:

- validates the result schema;
- compares actual diff with declared scope/class;
- checks acceptance evidence;
- runs focused gates;
- applies quality/deprecation checks;
- recomputes whether acceptance IDs closed;
- rejects self-reported progress unsupported by evidence.

### Phase 6 — Simplify

After focused green evidence:

- remove duplication and obsolete paths;
- reduce oversized-file responsibility;
- improve ownership/naming;
- preserve the focused gate;
- avoid unrelated cleanup.

### Phase 7 — Independent review

Normal risk: one independent reviewer.

Scientific/high risk: scientific and engineering reviewers in parallel.

Reviewers are read-only and inspect the actual full diff and evidence.

Consensus is used only when blocking reviewers materially disagree or a high-impact
decision is contested. It has finite rounds; no consensus blocks.

A builder never accepts its own task.

### Phase 8 — Two-phase integration

1. capture target HEAD;
2. create integration worktree;
3. apply candidate;
4. run focused and affected regression gates;
5. run quality/deprecation checks;
6. verify target HEAD unchanged;
7. apply transaction to target;
8. verify resulting HEAD;
9. record evidence;
10. mark accepted;
11. prune only after retention checks.

### Phase 9 — Checkpoint

The sole controller:

- updates snapshots with expected revision;
- appends one event transactionally;
- closes child threads;
- rotates/bounds raw logs;
- records acceptance delta;
- chooses exactly one next action.

### Phase 10 — Milestone/final gate

A milestone closes only on its end-to-end scenario and acceptance IDs.

Final success requires:

- every mandatory acceptance ID closed freshly;
- no critical/high unresolved review;
- integrated regressions green;
- quality/deprecation gates green;
- docs/state match implementation;
- handoff/resume verified;
- exact Git state recorded.

## Circuit breakers

1. Unchanged failing command: maximum two.
2. Same normalized failure: maximum three implementation attempts.
3. Then one root-cause diagnosis.
4. No new hypothesis after diagnosis: block.
5. Two checkpoints without acceptance delta: replan once, then block.
6. Environment correction: maximum one.
7. Expensive command repeats only after a material change.
8. Every wait/poll/process has a timeout.
9. Every lease expires.
10. No recursive children.
11. No overlapping writers.
12. No test/threshold/precision/resolution/coverage weakening.
13. No unrelated scope expansion.
14. No new logic in oversized legacy files without extraction/exception.
15. No expired deprecation.
16. A terminal state ends the run.

## Human boundaries

Explicit approval is required for:

- contract or threshold changes;
- new public/persistent compatibility commitments;
- destructive Git/data actions;
- merge/push/publish;
- license/ownership changes;
- deployment;
- cluster job mutation;
- unrestricted permissions.

## Terminal states

Assign exactly one:

- `AUTONOMOUS_RUN_SUCCEEDED`;
- `AUTONOMOUS_RUN_PAUSED_FOR_HANDOFF`;
- `AUTONOMOUS_RUN_SOLO_RECOMMENDED`;
- `AUTONOMOUS_RUN_BLOCKED_BY_CONTRACT`;
- `AUTONOMOUS_RUN_BLOCKED_BY_STATE_DIVERGENCE`;
- `AUTONOMOUS_RUN_BLOCKED_BY_ENVIRONMENT`;
- `AUTONOMOUS_RUN_BLOCKED_BY_NO_PROGRESS`;
- `AUTONOMOUS_RUN_BLOCKED_BY_REVIEW`;
- `AUTONOMOUS_RUN_FAILED_ACCEPTANCE`;
- `AUTONOMOUS_RUN_BUDGET_EXHAUSTED`.

For a non-success terminal state, write exact evidence and resume instructions.

## Final response

Return:

- terminal state;
- project/checkout/run;
- milestone and acceptance delta;
- accepted tasks;
- branch/HEAD/worktrees;
- validation and review;
- quality/deprecation result;
- evidence/handoff paths;
- blocker or success condition;
- exact next/resume command.

Do not ask a closing question.
