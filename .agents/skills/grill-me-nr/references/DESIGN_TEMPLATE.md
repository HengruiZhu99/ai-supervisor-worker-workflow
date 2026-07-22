# DESIGN.md template

Use this structure unless repository policy requires another format. Delete instructional text and irrelevant optional sections.

```markdown
# <Feature or change name>

- **Status:** READY_FOR_TDD | READY_FOR_TDD_WITH_ASSUMPTIONS | BLOCKED
- **Design revision:** 1
- **Objective:** <one sentence>
- **Authoritative scenario:** <scientist/user/operator-visible outcome>
- **Success authority:** <live system, executable validation, or independent artifact>
- **Affected subsystem:** <paths/components>
- **Question budget used:** <n of 6>

## Executive summary

<Chosen design and why it fits this repository.>

## Scope

### Required

- R1. <Individually testable requirement>
- R2. ...

### Non-goals

- ...

## Repository evidence

- `<path>` — <relevant architecture or convention>
- `<command>` — <baseline observation>

## Existing behavior and constraints

<Current data flow, APIs, tests, scientific conventions, compatibility, and resource limits.>

## Sources of truth and freshness

- **Authoritative current sources:** <paths, datasets, issues, APIs, commands, or commit SHAs>
- **Donor or archival sources:** <material that may inform the design but must not be treated as current>
- **Re-verification handles:** <cheap commands or procedures that re-establish load-bearing facts>

## Scientific and mathematical contract

<Equations, variable definitions, units, signs, index conventions, invariants, expected limits, and accuracy expectations. Use “not applicable” only when justified.>

## Chosen design

### Architecture and ownership

<Components and responsibilities.>

### Interfaces and data flow

<Inputs, outputs, lifetime, synchronization, error propagation, and persistence.>

### Algorithm or numerical method

<Method, discretization, boundaries/interfaces, initialization, update order, and exceptional cases.>

### Parallelism and performance

<MPI/thread/GPU behavior, decomposition, precision, memory, communication, and expected cost.>

### Diagnostics, restart, and reproducibility

<Observables, logging, checkpoint compatibility, seeds, determinism, and provenance.>

### Long-horizon execution constraints

<Scenario-centric work units, resource preflights, authoritative evidence, expected checkpoint boundaries, and state that must survive a fresh session or host transfer.>

## Alternatives considered

### Alternative A — <name>

- Advantages: ...
- Rejected because: ...

<At most three material alternatives.>

## Compatibility and migration

<API/file-format/restart impacts, transition strategy, and rollback.>

## Risks and mitigations

| Risk | Consequence | Mitigation or test evidence |
|---|---|---|
| ... | ... | ... |

## Decision ledger

| ID | Decision | Source or rationale | Reopen condition |
|---|---|---|---|
| D1 | ... | user / repository / default | only if ... |

## Assumptions

| ID | Assumption | Why safe/reversible | How TDD should validate it |
|---|---|---|---|
| A1 | ... | ... | ... |

## Open blockers

- None.

<For BLOCKED status, replace “None” with the exact conflict, evidence checked, and smallest required decision.>

## TDD handoff

- Requirements that must become contract tests: R1, ...
- Highest-risk failure modes: ...
- Existing validation assets to reuse: ...
- Baseline commands discovered: ...
- Performance or hardware caveats: ...
- Authoritative scenario and success authority: ...
- Facts that require re-verification after a handoff: ...
```
