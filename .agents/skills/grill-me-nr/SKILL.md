---
name: grill-me-nr
description: Produce a decision-complete design for numerical-relativity, scientific-computing, or HPC work. Inspect the repository first, ask only bounded decision-critical questions, write DESIGN.md, and stop before implementation. Use explicitly before tdd-nr or Goal mode.
---

# Grill Me NR

## Purpose

Turn a rough scientific-software objective into a reviewable, testable design without implementing it. Prefer evidence from the repository over questions. Ask the user only about uncertainties that materially change the scientific contract, public behavior, architecture, or acceptance target.

The normal output is `DESIGN.md` in the repository root. Read `references/DESIGN_TEMPLATE.md` before writing it.

## Operating contract

- Work in design-discovery mode only.
- Obey all applicable `AGENTS.md` files and repository policies.
- Do not modify production code, tests, dependencies, generated files, or build configuration.
- You may run safe read-only discovery commands and existing build or test commands when they help characterize the baseline.
- Do not launch Goal mode and do not begin implementation.
- Do not ask for generic approval. Finish the design, state its terminal status, and stop.

## Finite workflow

Follow these phases once, in order. Do not restart an earlier phase unless new user information directly contradicts a recorded decision.

### Phase 1: Frame the task

1. Restate the objective in one precise sentence.
2. Identify the requested outcome, affected subsystem, explicit constraints, and obvious non-goals.
3. Read any existing `DESIGN.md`; preserve accepted decisions unless the user explicitly supersedes them.
4. Create an internal uncertainty ledger with these fields:
   - unknown
   - evidence already checked
   - design impact
   - reversibility
   - recommended default
   - ask, assume, or block

Do not show the entire internal ledger unless it helps explain a blocking issue. Record final decisions and assumptions in `DESIGN.md`.

### Phase 2: Inspect before asking

Inspect enough of the repository to answer likely questions yourself. Start with:

1. Relevant `AGENTS.md`, `README`, architecture notes, build files, and CI configuration.
2. The requested subsystem, its callers, its data flow, and adjacent abstractions.
3. Existing tests, validation scripts, examples, benchmarks, and analogous implementations.
4. Conventions that affect correctness, including as applicable:
   - equations, variables, units, sign and index conventions
   - gauge, formulation, discretization, reconstruction, flux, boundary, and interface choices
   - precision, normalization, tolerances, and error norms
   - mesh, domain decomposition, MPI, threading, accelerator, and memory constraints
   - restart, checkpoint, I/O, diagnostics, and backward compatibility

Use one breadth pass followed by targeted lookups for unresolved high-impact items. Do not read the entire repository. Stop inspecting once you can identify the relevant entry points, constraints, analogous patterns, validation infrastructure, and remaining decision-critical uncertainties.

### Phase 3: Decide what deserves a question

Ask a question only when all of the following are true:

1. The answer materially changes at least one of: mathematical model, observable behavior, public API, persistent data, architecture boundary, compatibility promise, resource budget, or acceptance criterion.
2. The answer is not available from the repository, supplied documents, current conversation, or a safe command.
3. At least two plausible answers remain.
4. Choosing the wrong answer would be costly, scientifically invalid, hard to reverse, or likely to invalidate the test contract.

Do not ask about:

- code style, naming, file placement, or command syntax already established by the repository
- implementation details that can be selected locally and reversed cheaply
- facts discoverable from code, tests, docs, logs, or configuration
- speculative edge cases with no credible effect on the design
- generic prompts such as “anything else?”, “does this look good?”, or “should I continue?”

### Phase 4: Ask a bounded set of questions

Use this hard question policy:

- Default budget: 4 total questions.
- Absolute maximum: 6 total questions unless the user explicitly requests a deeper interview.
- Maximum per message: 3 questions.
- Maximum question messages: 2.
- Never repeat, rephrase, or reopen an answered question unless new evidence creates a direct contradiction.
- If the user says “use your judgment”, “use defaults”, or expresses no preference, accept the recommended defaults for all affected reversible choices and do not revisit them.
- If the user answers only part of a batch, use the recommended defaults for omitted reversible items instead of re-asking.

Every question must use this compact form:

```text
Q1 — <decision>
Why it matters: <one sentence naming the design or test consequence>
Options: A) ...  B) ...  [C) ... only when necessary]
Recommended default: <option and brief reason>
```

Group related decisions into one question when they share the same consequence. Do not disguise many unrelated questions as subparts.

After the second question message or the hard question cap:

- resolve remaining reversible uncertainties with the recommended defaults and record them as assumptions;
- mark only genuinely irreducible, high-impact conflicts as blockers;
- proceed to a terminal design state rather than continuing the interview.

### Phase 5: Select the design

For each material design branch:

1. Compare no more than three credible alternatives.
2. Evaluate scientific correctness, fit with existing architecture, validation difficulty, performance implications, migration cost, and reversibility.
3. Select one recommendation and explain why it dominates for this repository.
4. Record rejected alternatives briefly; do not produce an exhaustive survey.

The design must define, when relevant:

- one authoritative scientist/user/operator-visible scenario and the live system or artifact that decides whether it is true
- authoritative current sources versus donor, archival, or stale material
- cheap re-verification handles for load-bearing repository or external facts
- mathematical and physical contract
- scope and explicit non-goals
- architecture and ownership boundaries
- data structures and data flow
- public and internal interfaces
- algorithms and numerical methods
- boundary, interface, initialization, and failure behavior
- parallelism, accelerator, precision, memory, and performance considerations
- diagnostics, observability, restart, and reproducibility behavior
- long-horizon resource, checkpoint, and handoff constraints when the implementation may span sessions or hosts
- compatibility and migration strategy
- risks, mitigations, assumptions, and unresolved blockers
- a requirement list suitable for conversion into tests

### Phase 6: Run the completion gate

Write `DESIGN.md` using `references/DESIGN_TEMPLATE.md`. Assign exactly one terminal status:

- `READY_FOR_TDD`: no decision-critical unknown remains.
- `READY_FOR_TDD_WITH_ASSUMPTIONS`: only explicit, reversible assumptions remain.
- `BLOCKED`: at least one unresolved issue prevents a scientifically or architecturally coherent test contract.

A ready design must satisfy all of these checks:

- one unambiguous objective and authoritative observable scenario
- bounded scope and non-goals
- relevant current architecture described with file-level evidence
- chosen design and rejected material alternatives
- conventions and invariants stated explicitly
- interfaces and data flow defined
- failure and edge behavior defined
- compatibility and resource constraints addressed
- requirements are individually testable
- assumptions and decisions are recorded
- no unresolved item is mislabeled as a future implementation detail

If blocked, name the smallest user decision or missing evidence that would unblock the design. Do not keep searching or asking broad follow-ups.

## Loop guards

These rules are mandatory:

1. A resolved decision is immutable for this run unless contradicted by new user evidence.
2. Do not execute the same discovery command twice unless the query, path, or hypothesis changed materially.
3. Do not perform more than one targeted follow-up inspection for the same uncertainty without either resolving, assuming, or blocking it.
4. Do not create recursive tasks such as “investigate until fully certain.” Use the completion gate and terminal statuses instead.
5. Do not turn low-confidence but reversible implementation choices into user questions.
6. Do not silently invent a scientific convention. Derive it from evidence, ask within budget, or mark a blocker.
7. Once `DESIGN.md` is written and the terminal status is reported, stop. The next phase belongs to `$tdd-nr`.

## Final response

Return only a compact handoff containing:

- the `DESIGN.md` path
- terminal status
- chosen design in 2–4 sentences
- assumptions or blockers, if any
- suggested next invocation: `$tdd-nr Read DESIGN.md and produce the test contract and GOAL.md.`

Do not ask a closing question.
