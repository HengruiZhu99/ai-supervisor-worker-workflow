# Roadmap

## M0: Workflow and repository skeleton

Acceptance criteria:
- [ ] AI workflow files exist.
- [ ] Worker loop script validates with `bash -n`.
- [ ] Helper Python scripts compile.
- [ ] Job protocol is documented.
- [ ] Commit documentation protocol is documented.

## M1: Detailed design extraction

Acceptance criteria:
- [ ] `.ai/supervisor/design_prompt.md` contains the real project design.
- [ ] `.ai/supervisor/project_brief.md` is filled in.
- [ ] Roadmap is customized to the project.
- [ ] Initial scientific risks are listed in the ledger.

## M2: Minimal package/build/test skeleton

Acceptance criteria:
- [ ] Project has a reproducible build or test command.
- [ ] Basic smoke tests pass.
- [ ] Documentation explains how to run tests.

## M3: Reference implementations of core mathematical building blocks

Acceptance criteria:
- [ ] Simple readable reference implementations exist.
- [ ] Equations/references are documented.
- [ ] Unit tests cover basic correctness.

## M4: Unit tests and convergence tests

Acceptance criteria:
- [ ] Edge cases are tested.
- [ ] Deterministic seeds are used where relevant.
- [ ] Convergence rates are tested where relevant.
- [ ] Tolerances are justified.

## M5: Integration tests / small scientific problems

Acceptance criteria:
- [ ] Small end-to-end problems run.
- [ ] Regression outputs are documented.
- [ ] Failure modes are recorded.

## M6: Performance-portable implementation

Acceptance criteria:
- [ ] Optimized/backend implementation matches reference behavior.
- [ ] Backend parity tests exist where applicable.
- [ ] Performance-sensitive code paths are documented.

## M7: MPI/task-parallel implementation if applicable

Acceptance criteria:
- [ ] Serial and parallel results agree.
- [ ] Parallel edge cases are tested.
- [ ] Communication assumptions are documented.

## M8: Validation against analytic solutions, papers, or trusted codes

Acceptance criteria:
- [ ] Validation cases are documented.
- [ ] Results match expected references within justified tolerances.
- [ ] Discrepancies are recorded.

## M9: Documentation and reproducibility

Acceptance criteria:
- [ ] Clean checkout instructions exist.
- [ ] Main examples run.
- [ ] Accepted jobs and commits are summarized.

