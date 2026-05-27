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
- Accept or reject jobs.
- Update `.ai/supervisor/ledger.md`.
- Avoid loading huge logs unless necessary.
- Avoid polling while waiting for the worker.
- Avoid implementing worker jobs directly unless explicitly instructed by the user.

In milestone-gated autonomous mode, Codex may review completed jobs, accept or reject them, update the ledger, and dispatch the next small job without human input until the current milestone is complete or blocked. Human input is required at milestone boundaries, for scope changes, and for unresolved scientific or engineering decisions.

When a human milestone review requests a major structural change, Codex should treat the response as a planning revision. The revision job should update the roadmap, project brief, ledger, and related architecture documents, then create a new human review gate summarizing the changed milestones and proposed next worker jobs. Codex should not continue implementation until that revised plan is approved.

### Cursor worker

Cursor acts as the implementation worker.

Responsibilities:
- Implement exactly one assigned job.
- Work in an isolated Git worktree.
- Run requested tests.
- Write a concise report.
- Break changes into meaningful Git commits when possible.
- For each commit or attempt, record a documentation summary under `.ai/commit_docs/`.
- Never mark its own work as accepted.
- Never broaden scope without supervisor approval.

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
