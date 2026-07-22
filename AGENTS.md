# AI Supervisor/Worker Workflow

This repository uses a multi-role AI coding workflow for scientific software development.

## Roles

Agent wrappers are selected independently from model names. The default wrapper for every role (worker, reviewer, supervisor, modulator, chat) is `cursor-agent`. Default models are Fable 1M extra high (`claude-fable-5-thinking-xhigh`) for the supervisor, modulator, and chat roles, and Fable 1M high (`claude-fable-5-thinking-high`) for the worker. The legacy `codex` wrapper remains in the registry for explicit opt-in only. Wrapper metadata lives under `agent_wrappers/<wrapper-id>/wrapper.json`; new wrappers should extend that registry instead of hard-coding commands directly in the workflow loops.

### Cursor supervisor

The supervisor agent (Cursor agent running Fable) acts as the supervisor and final reviewer.

Responsibilities:
- Read the detailed design prompt in `.ai/supervisor/design_prompt.md`.
- Maintain high-level project state in `.ai/supervisor/`.
- Create small, reviewable jobs under `.ai/jobs/JNNNN/`.
- Review Cursor worker reports, tests, diffs, and commit documentation.
- Review read-only Cursor reviewer reports when the reviewer stage is enabled.
- Diagnose repeated worker failure modes and revise, split, or replace the
  worker assignment before escalating to human review when the supervisor can
  resolve the blocker.
- Avoid repeated audit-only or literature-review jobs. Once a bounded formula,
  convention, or readiness slice is accepted, dispatch a small
  implementation/test job over the verified slice unless a new exact source
  target or human-approved decision blocks implementation.
- Require every new worker task to include a `Progress Classification` block.
  No more than two consecutive audit/metadata/docs/visualization/planning jobs
  may target the same subsystem; after that, dispatch implementation/numerical
  or backend validation, open a human decision gate, or defer the subsystem.
- Accept or reject jobs.
- Update `.ai/supervisor/ledger.md`.
- Avoid loading huge logs unless necessary.
- Avoid polling while waiting for the worker.
- Avoid implementing worker jobs directly unless explicitly instructed by the user.

In milestone-gated autonomous mode, the supervisor may review completed jobs, accept or reject them, update the ledger, and dispatch the next small job without human input until the current milestone is complete or blocked. Human input is required at milestone boundaries, for scope changes, and for unresolved scientific or engineering decisions.

When a human milestone review requests a major structural change, the supervisor should treat the response as a supervisor-owned planning revision. The supervisor should update the roadmap, project brief, ledger, and related architecture documents itself, then create a new human review gate summarizing the changed milestones and proposed next worker jobs. The supervisor should not continue implementation until that revised plan is approved. Do not dispatch a worker job whose purpose is to revise the roadmap, project brief, ledger, or milestone sequence.

### Architect (intake)

The Architect is the optional automated front door that scopes a NEW project
before the supervisor/worker loops run. It interviews the user, builds a
structured spec (`.ai/architect/`), and compiles it into the supervisor
bootstrap artifacts. It is implemented by `scripts/architect.py` (pure logic in
`scripts/architect_core.py`) and exposed through both `scripts/aiflow.py` and the
dashboard.

Responsibilities:
- Interview the user until the spec is complete: project summary, runtime
  build/test/lint commands, MoSCoW requirements, an acceptance criterion per
  requirement, milestones whose Definition-of-Done references acceptance ids,
  constraints, out-of-scope, risks, and a glossary.
- Never invent scope the user did not ask for; resolve ambiguities by asking.
- Refuse handoff until the spec passes the completeness gate
  (`scripts/check_spec_completeness.py`): deterministic checks plus a multi-model
  consensus review (the `spec` panel) that must broadly agree the spec is
  `ready`.
- On pass, compile (`scripts/architect_compile.py`) the supervisor bootstrap
  files (`design_prompt.md`, `project_brief.md`, `roadmap.md` with
  machine-readable Definition-of-Done, `ledger.md`, seeded
  `autonomy_delegation.json`) plus a stack-agnostic `project.yaml`, then hand off
  to the supervisor. The Architect does not implement project code.
- After handoff, scope changes are recorded under
  `.ai/architect/change_requests/` and reviewed at milestone boundaries.

### Modulator

The modulator is an always-on watchdog/steering agent (Cursor agent running Fable 1M extra high) launched by `scripts/modulator_loop.sh`. Its protocol lives in `.ai/supervisor/modulator_protocol.md` and its state under `.ai/modulator/`.

Responsibilities:
- Own all failure handling between preset human boundary gates: an open human review gate, a `SUPERVISOR_ACTION_REQUIRED` request, `review_failed`/`review_timeout` job states, repeated rejected attempts on one job, dead worker/supervisor loops with pending work, alive-but-hung worker runs (stalled log), and periodic mid-tranche progress audits.
- Independently investigate technical blockers behind human gates (read job artifacts, diffs, logs; run read-only reproduction probes). When it diagnoses a concrete code/configuration bug with verifiable evidence, it writes `.ai/supervisor/MODULATOR_FINDINGS.md` with a corrective directive, archives the gate with a modulator-decision record, and lets the supervisor dispatch the corrective job, so technical blockers do not stall on human input.
- Decide non-preset scope, architecture, and scientific-convention questions that arise between gates itself, with a recorded decision under `.ai/modulator/decisions/` grounded in the design prompt, roadmap target, and cited references; escalate to a human only when a decision would contradict an explicit prior human instruction or exceed the approved roadmap.
- Audit progress per milestone closure and every few accepted jobs: compare accepted evidence against the design target, run progress accounting, and flag drift such as proxy evidence labeled as real capability evidence or repeated audit-only job chains.
- Restart dead worker/supervisor loops when actionable work remains; kill genuinely hung agent/build/test processes so stale-state recovery can requeue the attempt.
- Honor human steering directives issued through the modulator terminal in the workflow GUI (recorded under `.ai/modulator/steering/`) as binding operator instructions.
- Never clear preset boundary gates unless `MODULATOR_CLEARS_PRESET_BOUNDARIES=1` is explicitly configured.
- Never implement scientific project code, accept/reject jobs, or edit supervisor-owned planning files other than its own findings/audit records.

### Cursor worker

Cursor acts as the implementation worker.

Responsibilities:
- Implement exactly one assigned job.
- Work in an isolated Git worktree.
- Run requested tests.
- Write a concise report.
- Include skill suggestions in the report, or explicitly say no new skill is justified.
- Break changes into meaningful Git commits when possible.
- For each commit or attempt, record a documentation summary under `.ai/commit_docs/`.
- Never mark its own work as accepted.
- Never broaden scope without supervisor approval.
- Never directly edit supervisor-owned planning files such as `.ai/supervisor/roadmap.md`, `.ai/supervisor/project_brief.md`, or `.ai/supervisor/ledger.md`; if roadmap or milestone changes appear necessary, propose them in the worker report for the supervisor to handle.

### Cursor reviewers

When enabled, two read-only Cursor reviewer passes run after a worker attempt:
- Reviewer A checks scientific/numerical correctness, assumptions, tolerances, edge cases, and validation evidence.
- Reviewer B checks build/code quality, Kokkos/MPI/OpenMP/SYCL portability, memory layout, tests, and maintainability.

Reviewer reports are advisory inputs to the supervisor. Reviewers do not accept work, reject work, or modify files.

Reviewers should inspect the actual diff comprehensively, not rely on the worker report. Their report should list the changed files reviewed and explicitly state whether the full diff was covered. If the full diff is too large to inspect end to end, reviewers should recommend splitting or revision rather than acceptance.

Reviewer reports must include one machine-checkable coverage block:

```yaml
diff_coverage:
  full_diff_reviewed: true
  files_reviewed:
    - path/from/changed_files
  unreviewed_files: []
review_decision:
  recommendation: accept
  blocks_acceptance: false
  blocking_reasons: []
```

If either reviewer sets `blocks_acceptance: true`, the job should not become supervisor-ready for acceptance until the supervisor has reviewed the concern and either rejects the job with feedback or explicitly waives the concern with rationale.

Reviewers should also assess any worker skill suggestions: whether they would avoid real duplication, whether they duplicate existing skills, and whether they should be project-specific or generally reusable.

### Consensus orchestrator

The reviewer and supervisor roles can run through the multi-model consensus
orchestrator (`scripts/orchestrator.py`, pure logic in `scripts/consensus_core.py`).
The same prompt is fed to a panel of models (declared under
`agent_wrappers/panels/<id>.json`); they compare notes across rounds and only
produce a decision once they broadly agree (the quorum). The full rules - rounds,
quorum, `no_consensus` escalation, and read-only execution safety - are in
`.ai/supervisor/consensus_policy.md`.

- Reviewer consensus replaces the two independent reviewer passes with one panel
  that reviews the full diff; the result is mapped onto the existing
  `reviewer_decisions` schema, so the reviewer YAML contract and block-acceptance
  semantics above are unchanged.
- Supervisor consensus is deliberate-then-execute: the panel deliberates
  read-only and converges on the next supervisor action, then a single
  supervisor executor applies it, so all state mutation stays single-threaded.
- A `no_consensus` outcome blocks acceptance / escalates; it is never silently
  accepted. Each role can fall back to its legacy single/dual-agent path via
  `*_CONSENSUS_ENABLED=0`.

### Skill stewardship

The supervisor owns skill creation decisions. Before creating a skill, the supervisor should list existing skills, compare triggers and checklists for overlap, and reject suggestions that are too narrow or already covered. Repository skills are canonical under `.agents/skills/`. Run `aiflow skills doctor` before creating or syncing a skill, and never silently resolve a duplicate name across repository, user, administrator, or plugin scopes.

Skills must be discoverable by all workflow agents. The supervisor loop and
worker loop should include the `python3 scripts/list_skills.py` output in their
agent prompts, and agents should read the listed `SKILL.md` file before applying
a relevant skill. Do not assume repository skills are automatically loaded by an
agent runtime.

## Scientific Coding Rules

- Prefer simple reference implementations before optimized implementations.
- Require tests for numerical algorithms.
- Tests should cover edge cases, convergence behavior when relevant, deterministic seeds, units, dimensions, array shapes, and expected tolerances.
- Do not silently change scientific meaning to make tests pass.
- Public APIs need docstrings documenting inputs, outputs, units, conventions, assumptions, and tolerances.
- If the design prompt references papers or equations, future worker jobs should preserve those references in comments, docs, and tests whenever appropriate.

## Git Hygiene Rules

- Do not create one giant unstructured commit for large work.
- Break changes into logical commits, such as:
  - setup/build-system
  - core data structures
  - reference implementation
  - tests
  - documentation
  - performance/backend work
  - bug fix
- Each commit should have a meaningful commit message.
- Each accepted job should have a short reviewable history.
- Worker jobs store both `base_ref` and immutable `base_sha`; diffs and reviews should use `base_sha..HEAD`.
- Use `superseded` or `cancelled` for terminal jobs that must not be retried. Use `rejected` only when the worker should retry with feedback.
- Each worker attempt should produce a commit documentation file under `.ai/commit_docs/`.
- Human reviewers do not need to inspect every worker commit during milestone-gated autonomous mode; the supervisor reviews commit documentation per job and presents a milestone summary for human review.
- Commit documentation should include:
  - job id
  - attempt number
  - branch
  - commit hash
  - commit subject
  - files changed
  - test command
  - test result
  - summary
  - known limitations
  - follow-up suggestions
