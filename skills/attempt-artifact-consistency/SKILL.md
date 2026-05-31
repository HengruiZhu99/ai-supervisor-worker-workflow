---
name: attempt-artifact-consistency
description: Check that worker reports, commit docs, job status, git history, changed-file lists, and test logs describe the same worker attempt.
---

# Attempt Artifact Consistency

## When to Use

Use when reviewing or retrying a worker attempt, especially after a job was blocked
for stale reports, wrong attempt numbers, wrong commit hashes, missing test
records, or contradictory `uncommitted` documentation.

This skill is usually triggered by the Codex supervisor from audit artifacts such
as `attempt_consistency.attempt-N.md`, `status.json`, `feedback.md`, and
`.ai/commit_docs/`. The worker may also use it before writing a final report.

## Checklist

- Compare `status.json` attempt, final commit, test exit, and report paths
  against the current attempt artifacts.
- Use immutable `base_sha..HEAD` or `base_sha..commit` for attempt diff and
  commit-range checks.
- Confirm commit documentation filenames and body text use the current job id,
  attempt number, branch, final commit hash, and test result.
- Confirm commit documentation covers every commit in the attempt range, not only
  the last commit.
- Confirm `changed_files.attempt-N.txt`, diffstat, and commit docs describe the
  same changed files.
- Remove or replace stale canonical `*_uncommitted*`, wrong-attempt, or
  wrong-final-commit documentation before review.
- Ensure the final worker report does not contain stale claims that no commit was
  made, no validation ran, shell commands were rejected, or work is only
  uncommitted when the worker loop has created commits or run tests.
- Treat worker-written docs as supplemental if they contradict canonical
  worker-loop facts.
- Run `scripts/check_attempt_consistency.py` when available and block reviewer
  handoff if it reports issues.

## Output Format

When reporting a consistency decision, include:

1. Job id and attempt.
2. Base SHA and final commit.
3. Commit range and number of commits.
4. Canonical commit documentation file(s).
5. Test command/log/result.
6. Any contradictions found.
7. Required correction or confirmation that artifacts are consistent.

## Common Failure Modes

- A retry keeps a commit doc named for an earlier attempt.
- A commit doc records only the final metadata commit and omits the implementation
  commit in the same attempt range.
- A stale `*_uncommitted.md` file remains after the loop creates a fallback
  commit.
- The final report includes raw transcript text that contradicts the structured
  report summary.
- `status.json` points to one commit while commit docs or reports name another.
- Tests pass in the canonical test log, but the worker report still says
  validation could not run.
