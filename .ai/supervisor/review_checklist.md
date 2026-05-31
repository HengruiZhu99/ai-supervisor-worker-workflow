# Review Checklist

## Scope control

- [ ] Did the worker do exactly the assigned job?
- [ ] Did the worker avoid unrelated refactors?
- [ ] Did the worker avoid implementing future milestones prematurely?
- [ ] Is the diff small enough to review comprehensively?

## Diff review coverage

- [ ] Did each reviewer inspect the actual diff/worktree rather than relying on the worker report?
- [ ] Did reviewers use the immutable `base_sha..HEAD` diff range?
- [ ] Did reviewer reports list the changed files they reviewed?
- [ ] Did reviewer reports include the required `diff_coverage` YAML block?
- [ ] Does `scripts/check_reviewer_coverage.py` pass against `changed_files.attempt-N.txt`?
- [ ] Does `scripts/check_attempt_consistency.py` pass against the worker report, commit docs, status, and test log?
- [ ] Were all changed files reviewed, or were unreviewed paths explicitly listed?
- [ ] If the full diff was not reviewable, was the job rejected or split instead of accepted?

## Scientific correctness

- [ ] Are equations, references, assumptions, and conventions documented?
- [ ] Are units and dimensions clear?
- [ ] Are numerical tolerances justified?
- [ ] Are edge cases considered?
- [ ] Is scientific meaning preserved?

## Test quality

- [ ] Did the requested tests run?
- [ ] Did tests pass?
- [ ] Did tests leave the worker worktree clean after completion?
- [ ] Are new tests included for new behavior?
- [ ] Are stochastic tests deterministic?
- [ ] Are convergence tests included where relevant?
- [ ] Are regression or analytic validation tests included where relevant?

## Git and commit quality

- [ ] Are changes broken into meaningful commits where appropriate?
- [ ] Are commit messages clear?
- [ ] Does commit documentation exist under `.ai/commit_docs/`?
- [ ] Does the commit documentation match the actual diff and tests?

## Maintainability

- [ ] Are APIs documented?
- [ ] Are names clear?
- [ ] Is the implementation simple enough?
- [ ] Are performance-sensitive choices explained?

## Skill stewardship

- [ ] Did the worker include workflow friction or explicitly say none?
- [ ] Did the worker include skill suggestions or explicitly say none?
- [ ] Did reviewers assess workflow friction and skill suggestions?
- [ ] Are reported frictions better solved by a ledger note, docs, template/checklist/protocol update, script fix, project skill, or reusable workflow skill?
- [ ] Are any suggested skills non-duplicative and useful enough to create?
- [ ] Is each accepted skill classified correctly as project-specific or generally reusable?
- [ ] Were nontrivial decisions recorded in `.ai/supervisor/workflow_improvement_queue.md`, `.ai/supervisor/skill_decisions.md`, or the ledger?

## Decision

Choose one:

- [ ] Accept
- [ ] Reject with feedback
- [ ] Split into follow-up jobs
