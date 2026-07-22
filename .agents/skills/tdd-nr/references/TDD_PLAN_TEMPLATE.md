# TDD_PLAN.md template

Use this structure unless repository policy requires another format. Delete instructional text and irrelevant optional sections.

```markdown
# TDD plan: <feature or change>

- **Status:** READY_FOR_GOAL | READY_FOR_GOAL_WITH_ASSUMPTIONS | BLOCKED_BY_DESIGN | BLOCKED_BY_ACCEPTANCE_CRITERIA | BLOCKED_BY_ENVIRONMENT
- **Design source:** `DESIGN.md`, revision <n>
- **Objective:** <one sentence>
- **Authoritative scenario:** <observable vertical slice>
- **Success authority:** <live system, executable test, or independent artifact>
- **State directory:** `<tracked repository-relative path>`
- **Question budget used:** <n of 3>

## Baseline characterization

| Command or procedure | Environment | Result | Classification | Evidence | Re-verify handle |
|---|---|---|---|---|---|
| `...` | ... | pass/fail/not run | green / unrelated failure / target failure / environment failure | ... | `...` |

## Requirement-to-evidence matrix

| Req. | Failure risk | Test level | Independent oracle | Red evidence | Command/harness | Pass threshold | Environment | Re-verify handle | Class |
|---|---|---|---|---|---|---|---|---|---|
| R1 | ... | unit | analytic identity | expected mismatch ... | `...` | exact condition | ... | `...` | MANDATORY |

## Contract tests and immutable thresholds

| ID | Requirement | Test/procedure | Threshold | Rationale | Evidence artifact | Allowed change policy |
|---|---|---|---|---|---|---|
| CT1 | R1 | ... | ... | theory/baseline/reference | ... | strengthen freely; weakening requires contract change |

## Test design details

### Oracles and independence

<Explain why expected values do not reuse the implementation path.>

### Numerical tolerances and convergence

<Norms, units, resolutions, expected order, fit, margins, and precision.>

### Reproducibility and stochastic behavior

<Seeds, repetitions, confidence rule, nondeterminism allowance.>

### Parallel, device, and restart coverage

<Only relevant checks.>

### Performance and resource evidence

<Protocol, hardware, warmup, repetitions, baseline, target, preflight, alternate environment, and whether gating or informative.>

## Cheap-to-expensive gate ladder

| Level | Purpose | Command | Prerequisites | Resource minimum | Stop condition |
|---|---|---|---|---|---|
| 1 | static/config | `...` | none | ... | first failure |
| 2 | tiny probe | `...` | L1 | ... | first failure |
| 3 | negative/resource preflight | `...` | L1–L2 | ... | fail closed |
| 4 | smoke/component | `...` | L1–L3 | ... | first failure |
| 5 | milestone regression | `...` | L1–L4 | ... | first failure |
| 6 | full/expensive | `...` | all prior | ... | no identical retry without new evidence |

## Scenario-centric milestone DAG

`M1 -> M2 -> M3`

<The graph must be acyclic and each node must advance an observable scenario, not merely a repository or file set.>

## Milestones

### M1 — <observable slice>

- **Depends on:** none
- **Scenario delta:** ...
- **Contract:** R1, CT1
- **Red:** <test, command, and expected failure signature>
- **Builder boundary:** <smallest coherent implementation slice>
- **Focused validation:** `...`
- **Simplifier boundary:** <one bounded cleanup pass after green>
- **Independent audit:** <fresh/read-only rerun and artifact inspection>
- **Regression validation:** `...`
- **Evidence to retain:** ...
- **Resource preflight:** `...`
- **Exit:** <binary condition requiring audit>

<Repeat for each milestone.>

## Long-horizon execution state

### State artifacts

- `<state-directory>/IMPLEMENTATION_STATE.md`
- `<state-directory>/PROGRESS.jsonl`
- `<state-directory>/evidence/`
- `<state-directory>/repo-state.json`
- `<state-directory>/HANDOFF.md`
- `<state-directory>/RESUME_PROMPT.md`

### Truth and freshness policy

<Define trust classes, authoritative systems, donor/archive material, and the re-verification command attached to every load-bearing claim.>

### Forward-progress policy

<Define measurable checkpoint progress, normalized failure signatures, retry ceilings, no-progress ceiling, and expensive-command stop-loss.>

### Role separation

<Builder, simplifier, and independent auditor responsibilities; parallel-write restrictions.>

### Handoff and resume

<When `$handoff-nr` is invoked, how dirty work is preserved, and which resume handles must pass.>

## Final validation sequence

1. `...`
2. `...`
3. independent auditor rerun and artifact inspection

## Known baseline failures and exclusions

<Exact failures that are unrelated and therefore not falsely counted as regressions.>

## Acceptance assumptions

| ID | Assumption | Rationale | Validation or reopen condition |
|---|---|---|---|
| TA1 | ... | ... | ... |

## Blockers

- None.

<For a blocked status, replace “None” with the exact conflict, evidence, and smallest next decision or resource.>
```
