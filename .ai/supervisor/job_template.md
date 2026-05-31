# Job JNNNN: Title

## Objective

## Background from design prompt

## Scope

Allowed:
- ...

Not allowed:
- ...

## Scientific requirements

## Engineering requirements

## Git/commit requirements

- Break changes into meaningful commits when the task naturally separates into multiple parts.
- At minimum, create one commit for the attempt if files are changed.
- Do not mix unrelated refactors with implementation.
- Generate commit documentation under `.ai/commit_docs/`.
- The worker loop records `base_sha`; all review diffs use `base_sha..HEAD`.

## Files likely relevant

## Required validation

Run:

```bash
...
```

If validation intentionally generates untracked or modified files, list the expected paths or glob patterns in `.ai/jobs/JNNNN/allowed_artifacts.txt`. Otherwise the worker loop treats post-test dirty files as a blocking failure.

## Worker report contract

Return:

1. Summary
2. Files changed
3. Commits made
4. Tests run and results
5. Scientific assumptions
6. Known limitations
7. Suggested follow-up
8. Workflow friction
9. Skill suggestions

For workflow friction, return `None` if the task and workflow were clear. Otherwise list missing context, unclear instructions, repeated boilerplate, unavailable helper commands, painful manual steps, or places where a template/checklist/script would have prevented confusion.

For skill suggestions, return `None` if no new skill is justified. Otherwise include proposed name, scope (`project-specific` or `general scientific workflow`), when to use it, duplication risk versus existing skills, and the minimum content needed. Do not create or edit skills unless this job explicitly assigns workflow-maintenance work.
