---
name: scientific-code-review
description: Review scientific or numerical code written by a worker for correctness, scope, tests, and documentation.
---

# Scientific Code Review

## When to Use

Use when reviewing worker changes that implement or modify scientific, numerical, or data-analysis behavior.

## Checklist

- Confirm the diff stays within the assigned job scope.
- Confirm the job's progress classification is credible: executable behavior,
  numerical validation, backend validation, or a named implementation/test
  unblock.
- For audit/metadata/docs/visualization/planning jobs, verify that
  `unlocks_next` is specific and that acceptance would not continue a
  metadata-like streak for the same subsystem.
- Check mathematical meaning against the design prompt, equations, and references.
- Verify assumptions, units, dimensions, array shapes, tolerances, and conventions are documented.
- Inspect edge cases and failure modes.
- Confirm numerical tests cover relevant behavior and deterministic seeds are used where needed.
- Check that scientific meaning was not silently changed to make tests pass.
- Verify public APIs document inputs, outputs, units, assumptions, and tolerances.
- Confirm commit documentation exists and matches the actual diff and test results.
- Assess worker skill suggestions for actual reuse value and duplication against existing skills.

## Output Format

Return:
1. Decision: accept, reject, or split follow-up.
2. Findings ordered by severity.
3. Test assessment.
4. Scientific assumptions or risks.
5. Skill suggestion assessment.
6. Required feedback if rejected.

## Common Failure Modes

- Tests only check execution, not numerical correctness.
- Tolerances are widened without explanation.
- Units or dimensions are implicit.
- Worker implements future milestones without approval.
- Commit documentation omits failing tests or known limitations.
