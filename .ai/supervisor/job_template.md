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

Finish with a clean structured report using these exact Markdown headings:

1. Summary
2. Files Changed
3. Commits Made
4. Tests Run And Results
5. Scientific Assumptions
6. Known Limitations
7. Suggested Follow-Up
8. Workflow Friction
9. Skill Suggestions

Put only final attempt facts in the structured report. Do not copy stale
feedback, intermediate reasoning, old attempt claims, or raw tool transcripts
into the final structured report. The worker loop keeps the raw transcript
separately and extracts `worker_handoff.attempt-N.json` from this final report.

For workflow friction, return `None` if the task and workflow were clear. Otherwise list missing context, unclear instructions, repeated boilerplate, unavailable helper commands, painful manual steps, or places where a template/checklist/script would have prevented confusion.

For skill suggestions, return `None` if no new skill is justified. Otherwise include proposed name, scope (`project-specific` or `general scientific workflow`), when to use it, duplication risk versus existing skills, and the minimum content needed. Do not create or edit skills unless this job explicitly assigns workflow-maintenance work.
