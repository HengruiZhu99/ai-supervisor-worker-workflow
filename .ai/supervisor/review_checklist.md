# Review Checklist

## Scope control

- [ ] Did the worker do exactly the assigned job?
- [ ] Did the worker avoid unrelated refactors?
- [ ] Did the worker avoid implementing future milestones prematurely?

## Scientific correctness

- [ ] Are equations, references, assumptions, and conventions documented?
- [ ] Are units and dimensions clear?
- [ ] Are numerical tolerances justified?
- [ ] Are edge cases considered?
- [ ] Is scientific meaning preserved?

## Test quality

- [ ] Did the requested tests run?
- [ ] Did tests pass?
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

## Decision

Choose one:

- [ ] Accept
- [ ] Reject with feedback
- [ ] Split into follow-up jobs

