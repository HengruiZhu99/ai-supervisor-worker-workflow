# AI Supervisor/Worker Workflow

This repository uses a two-role AI coding workflow for scientific software development.

## Roles

### Codex supervisor

Codex acts as the supervisor and reviewer.

Responsibilities:
- Read the detailed design prompt in `.ai/supervisor/design_prompt.md`.
- Maintain high-level project state in `.ai/supervisor/`.
- Create small, reviewable jobs under `.ai/jobs/JNNNN/`.
- Review Cursor worker reports, tests, diffs, and commit documentation.
- Review read-only Cursor reviewer reports when the reviewer stage is enabled.
- Accept or reject jobs.
- Update `.ai/supervisor/ledger.md`.
- Avoid loading huge logs unless necessary.
- Avoid polling while waiting for the worker.
- Avoid implementing worker jobs directly unless explicitly instructed by the user.

In milestone-gated autonomous mode, Codex may review completed jobs, accept or reject them, update the ledger, and dispatch the next small job without human input until the current milestone is complete or blocked. Human input is required at milestone boundaries, for scope changes, and for unresolved scientific or engineering decisions.

When a human milestone review requests a major structural change, Codex should treat the response as a supervisor-owned planning revision. Codex should update the roadmap, project brief, ledger, and related architecture documents itself, then create a new human review gate summarizing the changed milestones and proposed next worker jobs. Codex should not continue implementation until that revised plan is approved. Do not dispatch a Cursor worker job whose purpose is to revise the roadmap, project brief, ledger, or milestone sequence.

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
- Never directly edit supervisor-owned planning files such as `.ai/supervisor/roadmap.md`, `.ai/supervisor/project_brief.md`, or `.ai/supervisor/ledger.md`; if roadmap or milestone changes appear necessary, propose them in the worker report for Codex to handle.

### Cursor reviewers

When enabled, two read-only Cursor reviewer passes run after a worker attempt:
- Reviewer A checks scientific/numerical correctness, assumptions, tolerances, edge cases, and validation evidence.
- Reviewer B checks build/code quality, Kokkos/MPI/OpenMP/SYCL portability, memory layout, tests, and maintainability.

Reviewer reports are advisory inputs to Codex. Reviewers do not accept work, reject work, or modify files.

Reviewers should inspect the actual diff comprehensively, not rely on the worker report. Their report should list the changed files reviewed and explicitly state whether the full diff was covered. If the full diff is too large to inspect end to end, reviewers should recommend splitting or revision rather than acceptance.

Reviewers should also assess any worker skill suggestions: whether they would avoid real duplication, whether they duplicate existing skills, and whether they should be project-specific or generally reusable.

### Skill stewardship

Codex owns skill creation decisions. Before creating a skill, Codex should list existing skills, compare triggers and checklists for overlap, and reject suggestions that are too narrow or already covered. Project-specific skills belong in this repository under `skills/`. Generally reusable scientific-coding workflow skills belong in the reusable workflow package under `external/ai-supervisor-worker-workflow/skills/` and should be committed and pushed there before updating the submodule pointer.

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
- Each worker attempt should produce a commit documentation file under `.ai/commit_docs/`.
- Human reviewers do not need to inspect every worker commit during milestone-gated autonomous mode; Codex reviews commit documentation per job and presents a milestone summary for human review.
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
