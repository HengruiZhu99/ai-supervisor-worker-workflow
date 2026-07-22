---
name: tdd-nr
description: Convert a ready DESIGN.md for numerical-relativity, scientific-computing, or HPC work into a falsifiable TDD contract, exact acceptance criteria, long-horizon state protocol, TDD_PLAN.md, and goal-ready GOAL.md. Inspect existing validation infrastructure, ask at most one small batch of test-critical questions, and stop before implementation.
---

# TDD NR

## Purpose

Translate an accepted scientific-software design into executable evidence of correctness and a finite implementation contract for Codex Goal mode. Define what must fail before the change, what must pass afterward, which commands prove it, how long-running state remains trustworthy across compaction or fresh sessions, and when autonomous work must stop.

The normal outputs are:

- `TDD_PLAN.md`;
- `GOAL.md`;
- a tracked repository-local state directory containing an initial `IMPLEMENTATION_STATE.md`, empty `PROGRESS.jsonl`, and `evidence/` directory.

Read these references before writing them:

- `references/TDD_PLAN_TEMPLATE.md`
- `references/GOAL_TEMPLATE.md`
- `references/SCIENTIFIC_TEST_CATALOG.md`
- `references/IMPLEMENTATION_STATE_TEMPLATE.md`
- `references/PROGRESS_EVENT_SCHEMA.md`

## Operating contract

- Work in test-contract and goal-handoff mode only.
- Obey all applicable `AGENTS.md` files and repository policies.
- Do not implement production code.
- Do not launch Goal mode.
- Do not weaken, delete, skip, quarantine, or silently loosen an existing test to make a future implementation easier.
- Normally do not create executable test files in this phase. Create test stubs only when the user explicitly requests them; otherwise specify them precisely in `TDD_PLAN.md` and `GOAL.md`.
- You may run safe baseline builds, tests, linters, examples, and benchmarks to characterize the current state.
- Do not design a long run that depends on chat memory as its source of truth.
- Finish with a terminal status and stop. Do not ask for generic approval.

## Finite workflow

Follow these phases once, in order. Do not cycle indefinitely between design, tests, thresholds, and implementation logistics.

### Phase 1: Gate the design input

1. Read `DESIGN.md`, the relevant `AGENTS.md` files, and any sources named by the design.
2. Accept `DESIGN.md` only when its status is:
   - `READY_FOR_TDD`, or
   - `READY_FOR_TDD_WITH_ASSUMPTIONS`.
3. If `DESIGN.md` is absent, internally inconsistent, or `BLOCKED`, do not reconstruct the entire design through a new interview. Write a compact `TDD_PLAN.md` with status `BLOCKED_BY_DESIGN`, identify the exact missing decision, recommend `$grill-me-nr`, and stop.
4. Treat the requirements, decision ledger, authoritative scenario, and explicit assumptions in `DESIGN.md` as the design contract. Do not silently change them.

If test planning exposes a contradiction in the design, propose one explicit design amendment. If that amendment materially changes scientific behavior, public behavior, architecture, persistent data, or compatibility, set the output status to `BLOCKED_BY_DESIGN` rather than guessing.

### Phase 2: Inspect the validation baseline

Inspect the repository before proposing tests:

1. Find the build, unit-test, integration-test, regression-test, benchmark, lint, sanitizer, and CI entry points that actually exist.
2. Inspect analogous tests and fixtures near the affected subsystem.
3. Identify independent oracles such as analytic solutions, manufactured solutions, identities, conserved quantities, reference data, cross-implementation comparisons, or trusted external artifacts already present in the repository.
4. Record relevant execution constraints:
   - required dependencies and datasets;
   - CPU, GPU, MPI, thread, precision, and platform requirements;
   - runtime, memory, disk, scheduler, and queue budgets;
   - deterministic versus stochastic behavior.
5. Run the narrowest useful existing baseline commands when feasible. Record exact commands, environment, pass/fail result, and relevant output signature.

Do not claim a green baseline when commands were not run or already fail. Classify known failures as:

- unrelated pre-existing failure;
- target-area failure that must become an initial repair milestone;
- environment failure that prevents a trustworthy contract.

For an environment failure, make at most one corrective attempt when the fix is obvious and safe. If it still fails, record the evidence and either define a non-local validation route or block the contract. Do not keep retrying.

### Phase 3: Define the authoritative scenario and work units

Long-horizon work should be organized around observable vertical slices, not merely files or repositories.

1. State the consumer-, scientist-, or operator-visible scenario that must become true.
2. Name the authoritative system or artifact that decides whether it is true.
3. Decompose work into dependency-ordered milestones that each move that scenario measurably closer to truth.
4. Avoid milestones such as “edit solver files” or “update repo A” unless they have a binary observable exit condition.
5. For multi-repository work, name the integration tuple and one owner of the end-to-end scenario. Do not let local repository success substitute for downstream truth.

### Phase 4: Map every requirement to falsifiable evidence

Create a requirement-to-evidence matrix. Every mandatory requirement from `DESIGN.md` must have at least one acceptance row with:

- requirement ID;
- failure risk being ruled out;
- test level;
- independent oracle or invariant;
- pre-implementation red evidence;
- exact command or harness;
- exact pass/fail threshold;
- required environment;
- re-verification handle;
- mandatory or informative classification.

Use the smallest credible test level first, then add broader evidence only for risks not covered below it. Suitable levels include:

- static/build/type checks;
- unit and algebraic tests;
- component and interface tests;
- regression and restart tests;
- manufactured or analytic-solution tests;
- convergence and consistency studies;
- conservation, constraint, or invariant monitoring;
- decomposition, rank, thread, device, or precision parity;
- long-time stability and physical validation;
- performance, memory, and scaling checks.

Select only relevant levels. Do not add a category merely because it exists in the catalog.

### Phase 5: Make criteria precise and independent

For every mandatory test, define all quantities needed to make the result objectively decidable:

- exact command and working directory;
- exit-code expectation;
- input or fixture;
- resolution, polynomial order, timestep, CFL, duration, or sample count;
- random seed and repetitions when applicable;
- norm, units, normalization, and comparison direction;
- absolute and/or relative tolerance;
- expected convergence order and fitting rule when applicable;
- allowed nondeterminism or statistical confidence rule;
- hardware and precision conditions for performance or parity gates;
- artifact or output that must be retained as evidence;
- cheap command that re-establishes the claim after a handoff.

Do not use vague criteria such as “close”, “small”, “stable”, “fast enough”, “looks correct”, or “reasonable”. Derive thresholds from one of:

1. mathematical theory or a known identity;
2. an analytic or manufactured solution;
3. a trusted independent reference;
4. an explicitly measured baseline plus a justified margin;
5. a user-selected scientific or product target.

The oracle must not duplicate the implementation path. Avoid self-fulfilling tests that compute expected values with the same formula, helper, table, or code path under test.

For performance tests, prefer a baseline-relative target with a defined measurement protocol. If the environment is too unstable for a gating threshold, mark the result `INFORMATIVE` rather than inventing false precision.

### Phase 6: Design a cheap-to-expensive gate ladder

Before any expensive build, long simulation, scaling run, or destructive environment operation, define a finite ladder such as:

1. syntax, format, static, and configuration checks;
2. tiny deterministic unit or algebraic probes;
3. negative preflight and resource checks;
4. focused component or smoke test;
5. milestone regression;
6. full build, long-time run, scaling study, or final integration test.

Each expensive command must name:

- its prerequisites;
- minimum CPU/GPU, memory, disk, queue, and wall-clock budget when relevant;
- one preflight command;
- maximum repeat count without new evidence;
- approved alternate environment or blocker condition.

Never make “retry the expensive command” the default next step after an environment or deterministic preflight failure.

### Phase 7: Ask only test-critical questions

Ask the user only when a falsifiable mandatory criterion cannot be chosen from the design, repository, theory, or baseline and the remaining choice is a genuine scientific or product decision.

Question budget:

- Maximum total: 3 questions.
- Maximum question messages: 1.
- Ask all necessary questions in one compact batch.
- Never re-ask a question answered in `DESIGN.md` or the conversation.
- If the user says “use defaults” or “use your judgment”, adopt the recommended reversible defaults and do not ask again.
- After the single question batch, resolve reversible issues with documented defaults. If an irreducible conflict remains, set `BLOCKED_BY_ACCEPTANCE_CRITERIA` and stop.

Use this format:

```text
Q1 — <acceptance decision>
Why it matters: <which mandatory gate changes>
Options: A) ...  B) ...
Recommended default: <option and evidence>
```

Do not ask about test file names, framework style, command syntax, state-directory naming, or implementation details already determined by the repository.

### Phase 8: Define milestone-based scientific TDD

Create an acyclic milestone plan. Each milestone must be independently reviewable and contain:

1. **Scenario:** the observable vertical slice advanced by this milestone.
2. **Contract:** requirement IDs and failure mode addressed.
3. **Red:** the test or falsification criterion to establish before production changes, including the expected failure signature.
4. **Green:** the smallest coherent implementation boundary and exact focused command that must pass.
5. **Simplify:** one bounded pass to remove unnecessary wrappers, duplication, or indirection while focused tests stay green.
6. **Audit:** an independent, preferably fresh-context rerun of the exact gate and artifact inspection.
7. **Regression:** broader commands required before advancing.
8. **Evidence:** outputs, metrics, plots, logs, state event, or artifacts to retain.
9. **Exit:** a binary milestone completion rule.

The builder owns production writes. A simplifier may edit only after focused green. An auditor is read-only with respect to the implementation being judged and must not accept builder summaries as evidence. Subagents may be used for read-heavy exploration, tests, and auditing; do not allow parallel writers to change the same files.

Not every pre-existing regression test will be red before implementation. Mark such tests `BASELINE_GREEN_REGRESSION`. New behavior tests should normally demonstrate red evidence first. When red demonstration is impossible or unsafe, document the reason and define another falsification step before implementation.

Identify a small set of **contract tests** and **contract thresholds** that Goal mode may not weaken. Goal mode may add stronger tests, but it may not remove or loosen these gates without pausing for a material contract change.

### Phase 9: Design durable long-horizon state

Choose a tracked repository-local state directory. Default to a project documentation location such as:

```text
docs/codex/<goal-slug>/
```

Use another path when repository policy requires it. Do not use the operating system temporary directory or an ignored path as the only authoritative state.

Initialize:

- `IMPLEMENTATION_STATE.md` from `references/IMPLEMENTATION_STATE_TEMPLATE.md`;
- an empty `PROGRESS.jsonl` governed by `references/PROGRESS_EVENT_SCHEMA.md`;
- `evidence/`;
- placeholders for `repo-state.json`, `HANDOFF.md`, and `RESUME_PROMPT.md`.

The execution contract must enforce:

- a compact mutable snapshot plus append-only history;
- contract fingerprints for `DESIGN.md`, `TDD_PLAN.md`, and `GOAL.md`;
- exact branch, commit, worktree, and environment addresses;
- one active milestone, one hypothesis, and one next action;
- truth classes for claims and a re-verification handle for every load-bearing claim;
- normalized failure signatures and retry/no-progress counters;
- active versus donor/archive artifact classification;
- atomic checkpoint updates;
- a handoff trigger at a clean milestone boundary, before host/session transfer, or when the user explicitly requests a fresh context;
- `$handoff-nr` as the transition protocol.

The state packet is an index, not an oracle. A fresh session must dereference the named commands and live systems before acting.

### Phase 10: Write the artifacts

Write `TDD_PLAN.md` using `references/TDD_PLAN_TEMPLATE.md`.

Write `GOAL.md` using `references/GOAL_TEMPLATE.md`. `GOAL.md` must be self-contained enough for a long Goal run and must include:

- one objective, one authoritative scenario, and one success condition;
- required input files to read first;
- scope and non-goals;
- ordered scenario-centric milestones;
- immutable contract tests and thresholds;
- exact validation commands and gate ladder;
- state-directory and checkpoint protocol;
- builder/simplifier/auditor separation;
- resource preflights and alternate environments;
- progress evidence requirements;
- change-control rules;
- finite retry, no-progress, and expensive-command guards;
- success, handoff, pause, and blocker conditions.

Assign exactly one terminal status:

- `READY_FOR_GOAL`: every mandatory requirement has an executable or objectively reproducible gate, durable state is initialized, and no blocker remains.
- `READY_FOR_GOAL_WITH_ASSUMPTIONS`: only explicit, reversible acceptance assumptions remain.
- `BLOCKED_BY_DESIGN`: the design is missing or contradictory.
- `BLOCKED_BY_ACCEPTANCE_CRITERIA`: a mandatory pass/fail decision cannot be made safely.
- `BLOCKED_BY_ENVIRONMENT`: no trustworthy validation route is currently available.

A ready status requires all of these checks:

- every mandatory design requirement maps to evidence;
- every mandatory gate has a command or reproducible procedure;
- every mandatory gate has an exact threshold and rationale;
- the independent oracle is identified;
- baseline state is honest and recorded;
- milestones are scenario-centric and acyclic;
- cheap gates precede expensive ones;
- Goal mode has finite stopping and retry rules;
- durable state includes re-verification handles and contract fingerprints;
- no test can be silently weakened to claim success;
- success requires an independent final audit, not only builder evidence.

## Required Goal-mode loop guards

Copy these semantics into `GOAL.md`, adapted to the repository:

1. Work on one active milestone and one falsifiable hypothesis at a time.
2. Establish the milestone's red or falsification evidence before changing production code.
3. Make one focused change, then run the cheapest relevant gate before broader validation.
4. Do not rerun the same failing command more than twice without a material change to code, configuration, input, resource state, or diagnostic hypothesis.
5. After three implementation attempts with the same normalized failure signature, stop patching and perform root-cause diagnosis. If no new testable hypothesis results, record a blocker and pause.
6. If two consecutive checkpoints produce no measurable movement on a mandatory gate, pause with evidence instead of continuing.
7. Before an expensive command, pass its static/tiny/negative/resource preflights. Never repeat an expensive failure without new evidence.
8. For a dependency, permission, hardware, dataset, or environment failure, make at most one safe corrective attempt; then use an approved alternate validation route or pause as blocked.
9. Never delete, skip, quarantine, lower precision, widen tolerance, reduce duration, reduce resolution, or narrow coverage merely to obtain a pass.
10. A contract test or threshold may change only when proven inconsistent with `DESIGN.md` or objectively defective. Record the evidence and pause for user input if the change weakens the accepted contract.
11. Treat stored state as a pointer. Re-run the named handle before relying on a claim after handoff, compaction, external change, or a meaningful delay.
12. Update `IMPLEMENTATION_STATE.md` atomically and append `PROGRESS.jsonl` after each meaningful checkpoint; do not use chat memory as the ledger.
13. Use builder -> simplifier -> independent auditor before closing a milestone. The auditor must rerun exact commands and inspect retained artifacts.
14. Do not expand scope to unrelated cleanup, architecture migration, dependency upgrades, or speculative optimization.
15. Ask the user only for an irreversible/high-impact decision, a direct contract conflict, or a safety/security boundary. Group at most three questions in one message and provide defaults.
16. Declare success only when every mandatory gate and the final independent regression/audit pass.
17. On a blocker, report the exact command, failure signature, attempts, artifacts changed, current safe state, smallest missing decision/resource, and safe resume point.
18. Before a fresh session or host transfer, pause at a recoverable checkpoint and invoke `$handoff-nr`; do not create recursive handoffs.

## Loop guards for this skill

1. Do not enter the implementation loop yourself; produce the contract and stop.
2. Do not bounce between `DESIGN.md` and test planning more than once. A material contradiction becomes a terminal blocker.
3. Do not repeatedly tune a tolerance to current output. Choose it from independent evidence or block it.
4. Do not create an unbounded test inventory. Every test must map to a named requirement or material failure risk.
5. Do not make performance optimization open-ended. Define a target, measurement budget, and stop condition.
6. Do not create more than one state directory for the same goal.
7. Once artifacts, initialized state, and terminal status are written, stop.

## Final response

Return only a compact handoff containing:

- `TDD_PLAN.md` path;
- `GOAL.md` path when a ready contract was created;
- state-directory path;
- terminal status;
- mandatory gate and long-horizon protocol summary;
- assumptions or blockers, if any;
- the copy-paste command:

```text
/goal Implement GOAL.md. Read DESIGN.md, TDD_PLAN.md, and the initialized IMPLEMENTATION_STATE.md first. Work one scenario-centric milestone at a time using red -> green -> simplify -> independent audit. Update the durable state after every meaningful checkpoint, re-verify stored claims before acting, and stop only on the documented success, handoff, or blocker condition.
```

Do not ask a closing question.
