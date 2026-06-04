---
name: cursor-worker-dispatch
description: Create a small, scoped worker job for Cursor using the filesystem job protocol.
---

# Cursor Worker Dispatch

## When to Use

Use when creating a new job under `.ai/jobs/JNNNN/` for Cursor to implement.

## Checklist

- Create exactly one job unless explicitly asked otherwise.
- Make the job small enough for a concise diff and one to three logical commits.
- State a clear objective and acceptance criteria.
- Include the mandatory `Progress Classification` block with concrete
  `job_type`, `subsystem`, `capability_target`, `validation_class`,
  `unlocks_next`, and `metadata_only` values.
- Include only the relevant design prompt excerpt.
- Define allowed and not allowed scope.
- Specify required tests or validation commands.
- Require a concise report.
- Require a `Skill Suggestions` report section, with `None` if no new skill is justified.
- Require meaningful commits and commit documentation.
- Avoid asking the worker to read the entire design prompt unless necessary.
- Do not dispatch more than two consecutive audit/metadata/docs/visualization
  jobs for the same subsystem; after two, dispatch implementation or validation,
  open a human gate, or defer that subsystem.

## Output Format

The job task should include:
1. Objective.
2. Background from design prompt.
3. Progress Classification.
4. Allowed and not allowed scope.
5. Scientific requirements.
6. Engineering requirements.
7. Git and commit requirements.
8. Required validation.
9. Worker report contract.
10. Skill suggestion contract.

## Common Failure Modes

- Job is too broad.
- Acceptance criteria are vague.
- Worker is given unrelated design details.
- Test command is missing.
- Scope permits unreviewable refactors.
