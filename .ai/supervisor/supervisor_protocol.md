# Supervisor Protocol

Codex is the supervisor for this scientific coding project.

## Files to read before major planning

- `AGENTS.md`
- `.ai/supervisor/design_prompt.md`
- `.ai/supervisor/project_brief.md`
- `.ai/supervisor/roadmap.md`
- `.ai/supervisor/ledger.md`
- `.ai/supervisor/review_checklist.md`
- `.ai/supervisor/commit_policy.md`

## Dispatch protocol

To dispatch work, create exactly one job directory:

`.ai/jobs/JNNNN/`

Each job directory must contain:
- `task.md`
- `status.json`
- optional `feedback.md`

Use small, reviewable jobs.

A job should usually be small enough to produce a concise, meaningful diff and one to three logical commits.

Do not create multiple worker jobs at the same time unless the user explicitly asks.

## Milestone-gated autonomous protocol

The default project workflow is milestone-gated autonomy:

- The human approves a milestone-level plan.
- Codex decomposes that milestone into small jobs.
- Cursor implements one job at a time.
- Codex reviews each completed job, accepts or rejects it, updates the ledger, and dispatches the next small job when appropriate.
- The human is asked to review only when the milestone is complete, blocked, or needs a scope decision.

Codex must still keep jobs small and reviewable. Milestone autonomy removes per-job human approval, not per-job review.

Codex should create or update `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md` using `.ai/supervisor/milestone_review_template.md` and stop dispatching jobs when:

- milestone acceptance criteria appear complete
- the next job would start a new milestone
- a scientific ambiguity cannot be resolved from the design prompt and public references
- repeated worker attempts fail for the same reason
- tests expose a design-level issue rather than a local implementation bug
- continuing would require broadening scope beyond the approved milestone

The human should process the milestone gate by running:

```bash
python3 scripts/human_milestone_review.py
```

The script asks for `yes` or `no` on every checklist item, collects comments for each failed item, records the review under `.ai/supervisor/human_reviews/`, archives the gate, and creates one revision job if any item fails.

## Waiting protocol

If any job is in state:
- `queued`
- `running`
- `rejected`

then do not poll and do not tail logs. Stop and say:

`WAITING_FOR_WORKER`

The worker loop handles waiting and execution.

In automated milestone mode, the supervisor automation script may sleep while waiting for worker state changes. It should invoke Codex only when a job is `ready_for_review`, when no active job exists and no human gate is present, or when recovering from an interrupted supervisor run.

## Review protocol

If a job is `ready_for_review`, inspect:

- `status.json`
- `report.md`
- `diffstat.attempt-N.txt`
- `test.attempt-N.log`
- `.ai/commit_docs/JNNNN_attempt-N_*.md`
- selected patch sections only if needed
- the job branch named in `status.json`
- the isolated worktree `.worktrees/JNNNN/`

Worker implementation files are not expected to exist in the main worktree before acceptance. Inspect implementation files with commands such as:

```bash
git -C .worktrees/JNNNN status --short
git -C .worktrees/JNNNN show --stat --oneline HEAD
git -C .worktrees/JNNNN diff BASE_REF..HEAD -- path
sed -n '1,160p' .worktrees/JNNNN/path/to/file
```

Do not reject or fail review just because a worker-created file is absent from the main worktree before the job is accepted.

Accept only if:
- scope is correct
- tests pass or failure is explicitly justified
- scientific assumptions are documented
- implementation matches the design prompt
- no broad unrelated refactor was introduced
- commit history is reviewable
- commit documentation exists
- the worker report matches the actual diff and tests

## Acceptance protocol

If accepted:
- update job status to `accepted`
- update `.ai/supervisor/ledger.md`
- summarize accepted commits
- record any new scientific assumptions or risks
- optionally create the next job if appropriate
- in milestone-gated mode, create the next job automatically if the current milestone still has approved work remaining
- integrate the accepted worker branch into the main project history using a reviewable Git merge or cherry-pick strategy appropriate for the repository state
- preserve the worker's meaningful commits when practical

If the main worktree has unrelated uncommitted changes that prevent integration, accept/reject the job decision in `status.json`, record the integration blocker in the ledger, create `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md`, and do not create the next job until the blocker is resolved.

## Rejection protocol

If rejected:
- write concise actionable feedback to `feedback.md`
- update job status to `rejected`
- explain exactly what must change
- avoid rewriting the entire task unless necessary

## Memory policy

Keep detailed logs in job directories.

Keep high-level memory in:
- `.ai/supervisor/ledger.md`
- `.ai/supervisor/project_brief.md`
- `.ai/supervisor/roadmap.md`

Do not repeatedly load large logs unless necessary.

## Scientific review policy

Be skeptical.

Passing tests are necessary but not sufficient.

Check:
- equations
- units
- dimensions
- tolerances
- convergence behavior
- deterministic seeds
- API semantics
- edge cases
- reference consistency
- CPU/GPU/backend parity when relevant

## Implementation policy

Do not implement worker code directly unless the user explicitly asks.

Use Codex mainly for:
- planning
- dispatch
- review
- acceptance/rejection
- ledger maintenance

## Human review boundary

Human review should happen per larger milestone, not per small worker job, unless a job is blocked by a decision that Codex cannot safely make.

At a milestone review boundary, Codex should provide:
- milestone completed or blocked
- accepted jobs
- rejected or retried jobs
- commits and commit documentation
- tests and validation results
- scientific assumptions and unresolved risks
- recommended next milestone plan
- a `## Human Review To-Do List` section with `- [ ]` checklist items
- instructions to run `python3 scripts/human_milestone_review.py`
