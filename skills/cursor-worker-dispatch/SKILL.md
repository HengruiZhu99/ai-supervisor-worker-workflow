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
- Include only the relevant design prompt excerpt.
- Define allowed and not allowed scope.
- Specify required tests or validation commands.
- Require a concise report.
- Require a `Skill Suggestions` report section, with `None` if no new skill is justified.
- Require meaningful commits and commit documentation.
- Avoid asking the worker to read the entire design prompt unless necessary.

## Output Format

The job task should include:
1. Objective.
2. Background from design prompt.
3. Allowed and not allowed scope.
4. Scientific requirements.
5. Engineering requirements.
6. Git and commit requirements.
7. Required validation.
8. Worker report contract.
9. Skill suggestion contract.

## Common Failure Modes

- Job is too broad.
- Acceptance criteria are vague.
- Worker is given unrelated design details.
- Test command is missing.
- Scope permits unreviewable refactors.
