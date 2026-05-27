# Commit Policy

The AI workflow should produce reviewable Git history.

## General principles

- Prefer several meaningful commits over one giant commit.
- Each commit should correspond to one coherent change.
- Commit messages should be specific.
- Do not mix unrelated refactors with scientific implementation.
- Do not mix tests and implementation if separating them improves reviewability.
- Do not hide failing tests by changing tolerances without explanation.

## Suggested commit categories

- `setup: ...`
- `docs: ...`
- `tests: ...`
- `refactor: ...`
- `impl: ...`
- `fix: ...`
- `perf: ...`
- `workflow: ...`

## Worker commit behavior

For each worker job attempt:
1. Work in the job worktree.
2. Make logical commits when the task naturally separates into pieces.
3. At minimum, create one commit for the attempt if there are changes.
4. Run the requested tests.
5. Generate commit documentation under `.ai/commit_docs/`.

## Commit documentation

Each documentation file should include:
- Job id
- Attempt number
- Branch
- Commit hash
- Commit subject
- Files changed
- Diff stat
- Test command
- Test exit code
- Test log path
- Summary
- Known limitations
- Suggested follow-up

## Supervisor review behavior

The supervisor should check:
- Whether the commit history is logically split.
- Whether commit documentation exists.
- Whether tests were run.
- Whether the summary matches the actual diff.
- Whether the implementation stayed in scope.

In milestone-gated autonomous mode, Codex performs this check for each worker job and summarizes commit quality at the milestone review boundary. Human review of every individual commit is optional unless Codex flags a risk.
