---
name: tdd-solo
description: Implement one bounded feature, bug fix, refactor, numerical test, portability change, or performance correction in an existing or new repository using one agent, evidence-first TDD, durable project-isolated state, strict scope, and finite stop conditions. Never launch subagents.
---

# TDD Solo

## Purpose

Complete one coherent engineering objective with one agent.

Use this skill for bounded work in existing repositories such as AthenaK as well as new
code. Do not invoke the supervisor, worker queue, modulator, consensus, or any subagent.

This skill uses the deterministic `aiflow` CLI for identity, leases, state, evidence, and
quality checks. If the required CLI is unavailable or incompatible, stop as
`SOLO_TDD_BLOCKED_BY_ENVIRONMENT`; do not invent a second state format.

## Inputs

- the user’s objective;
- applicable `AGENTS.md`;
- repository code, tests, build files, and conventions;
- optional issue/spec/reference;
- optional accepted thresholds or scientific contract.

A full `DESIGN.md` or `GOAL.md` is not required for a bounded task.

## Hard constraints

- One agent.
- One active task.
- One worktree.
- No subagents.
- No automatic escalation to the full workflow.
- No push, merge, publication, destructive reset, or cluster-job mutation.
- Preserve pre-existing user work.
- Do not weaken acceptance criteria to pass.
- Once a terminal state is recorded, stop.

## Question budget

Normal: zero.

Hard maximum:

- one question message;
- at most two questions;
- only when the answer materially changes scientific behavior, public compatibility, or
  the pass/fail contract and cannot be derived from repository evidence.

Use documented defaults for reversible implementation choices.

## Finite workflow

### Phase 0 — Resolve the project

1. Resolve the project from explicit root or current Git repository.
2. Verify logical project, checkout, worktree, and run identity.
3. Scrub inherited workflow context.
4. Acquire one solo controller/worktree lease.
5. Record branch, HEAD, dirty/staged/untracked state, and configuration hash.
6. Refuse a wrong-checkout or overlapping mutating run.
7. Preserve pre-existing changes.

If relevant target files have ambiguous overlapping user edits, stop as
`SOLO_TDD_BLOCKED_BY_STATE_DIVERGENCE` rather than overwriting them.

### Phase 1 — Inspect narrowly

Read:

- applicable repository instructions;
- entry points and callers for the target behavior;
- analogous implementations;
- relevant tests and fixtures;
- build/test commands;
- scientific/API conventions;
- current deprecations and quality policy.

Perform one breadth pass and targeted follow-ups. Do not read the whole repository.

### Phase 2 — Write the compact task contract

Record in the run state:

- objective;
- task type;
- user-visible or scientist-visible behavior;
- acceptance IDs;
- non-goals;
- relevant files/symbols;
- invariants/conventions;
- exact focused gate;
- broader regression gate;
- evidence paths;
- expected diff budget;
- one next action.

Classify as one of:

```text
feature
bugfix
refactor
test
numerical
performance
portability
documentation-explicit-goal
```

If the task contains several independently shippable objectives, recommend orchestrated
mode and stop as `SOLO_TDD_ORCHESTRATION_RECOMMENDED`. Do not launch it.

### Phase 3 — Establish baseline and falsification

Choose the correct evidence-first cycle.

#### Feature

Write or strengthen a test that fails for the intended missing behavior.

#### Bug fix

Reproduce the defect, then create a failing regression test.

#### Refactor

Create or confirm characterization tests before changing structure. A fake red test is
not required; behavior preservation is the contract.

#### Test-only

Demonstrate discriminating power using a negative control, mutation, known-bad case,
analytic oracle, or independent implementation.

#### Numerical

Pre-register norm, domain, resolution(s), tolerance, expected order/identity, exclusions,
and oracle before inspecting candidate output.

#### Performance

Record a correctness guard, equivalent-work invariant, warmup policy, repeated baseline,
and comparability fields.

Store command, exit status, observed result, and why it proves the intended baseline.

### Phase 4 — Implement the smallest coherent change

- Stay inside the contract.
- Follow existing architecture.
- Prefer a simple reference path before optimization.
- Do not add a new responsibility to an oversized legacy file.
- Remove superseded code when parity is proven.
- Do not create speculative abstractions.
- Do not alter unrelated APIs, dependencies, formats, or configuration.
- Do not use deprecated APIs for new code.
- Keep public scientific/API documentation current.

### Phase 5 — Focused GREEN

Run the focused gate.

If it fails:

1. normalize the failure signature;
2. state one falsifiable hypothesis;
3. make one coherent correction;
4. rerun only when code/input/environment/hypothesis changed.

Do not rerun an unchanged failure more than twice.

After three implementation attempts with the same signature, switch to root-cause
diagnosis. If no new testable hypothesis results, stop.

### Phase 6 — Refactor and simplify

With focused green evidence:

- improve names and ownership;
- reduce duplication;
- extract coherent logic from oversized files;
- remove obsolete compatibility code when allowed;
- keep the focused gate green.

Do not perform unrelated cleanup.

### Phase 7 — Verification ladder

Run, as applicable:

1. syntax/static checks;
2. focused test;
3. affected component tests;
4. affected regression suite;
5. numerical/scientific validation;
6. backend/MPI/device parity;
7. performance comparison;
8. quality and deprecation checks;
9. `git diff --check`.

Every expensive gate receives a resource preflight.

No-test-discovered, silent skip, weakened tolerance, or changed workload is a failure.

### Phase 8 — Cold self-review

Re-open the compact contract and inspect the full diff from scratch.

Check:

- every changed file;
- behavior and failure paths;
- scientific/API conventions;
- test independence;
- scope and non-goals;
- documentation;
- quality budgets;
- deprecated code;
- accidental generated/user files;
- evidence freshness.

This is a self-review, not independent review. Say so.

For a high-risk scientific or concurrency change, recommend a separate explicit reviewer
skill after solo completion. Do not invoke it automatically.

### Phase 9 — Checkpoint and stop

Update the durable run state and record:

- final branch/HEAD/status;
- changed files;
- commands and results;
- acceptance IDs closed;
- evidence paths;
- limitations;
- follow-ups;
- exact resume command if blocked.

Release the lease.

## Scope and progress breakers

- Two checkpoints without acceptance delta: stop and recommend re-scope or orchestration.
- One environment correction maximum.
- One active hypothesis.
- One active task.
- No hidden housekeeping while a delivery gate remains.
- Do not turn research into repeated implementation jobs.
- Do not ask “should I continue?”
- Do not start a second objective.

## Quality breakers

- New source file above the hard policy limit: split coherently.
- Existing oversized file grows without an expiring exception: fail.
- New deprecated call site: fail.
- Project-specific absolute path or toolchain logic in generic workflow code: fail.
- Actual diff above twice the expected budget: stop and split or document why solo remains
  safe.

## Terminal states

Assign exactly one:

- `SOLO_TDD_COMPLETE`;
- `SOLO_TDD_COMPLETE_WITH_DOCUMENTED_LIMITATIONS`;
- `SOLO_TDD_ORCHESTRATION_RECOMMENDED`;
- `SOLO_TDD_BLOCKED_BY_SPEC`;
- `SOLO_TDD_BLOCKED_BY_ENVIRONMENT`;
- `SOLO_TDD_BLOCKED_BY_STATE_DIVERGENCE`;
- `SOLO_TDD_BLOCKED_BY_NO_PROGRESS`;
- `SOLO_TDD_FAILED_ACCEPTANCE`.

## Final response

Return:

- terminal state;
- objective and acceptance IDs;
- changed files;
- focused and broader validation;
- quality/deprecation result;
- branch/HEAD/dirty status;
- evidence path;
- limitations;
- exact next or resume command.

Do not ask a closing question.
