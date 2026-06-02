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
- `.ai/supervisor/workflow_improvement_queue.md`, if present
- `.ai/supervisor/skill_decisions.md`, if present

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
- tests expose a design-level issue rather than a local implementation bug
- continuing would require broadening scope beyond the approved milestone

Repeated worker attempts that fail for the same reason are supervisor action
signals, not automatic human gates. Before stopping for human review, Codex must
inspect the actual failure mode across attempts, compare it to the job prompt
and available workflow capabilities, and choose the smallest supervisor-owned
correction that can unblock progress. Valid corrections include rewriting
`feedback.md`, revising the active job task before requeueing it, superseding
the failed job with a narrower replacement job, splitting the work into a
sequence, pre-staging non-private reference material or deterministic context
the worker is allowed to use, adjusting validation instructions, or opening
`.ai/supervisor/SUPERVISOR_ACTION_REQUIRED.md` for an operational repair. Open a
human gate only when the diagnosis leaves an unresolved human, scope,
architecture, or scientific decision that Codex cannot safely make.

The human should process the milestone gate by running:

```bash
python3 scripts/human_milestone_review.py
```

The script asks for `yes` or `no` on every checklist item, collects comments for each failed item, records the review under `.ai/supervisor/human_reviews/`, archives the gate, and creates `.ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md` if any ordinary checklist item fails. The Codex supervisor must read that request and decide whether to create a small worker revision job, split work into a sequence, update supervisor-owned plans, or open a clarification gate.

## Waiting protocol

If any job is in state:
- `queued`
- `running`
- `rejected`

then do not poll and do not tail logs. Stop and say:

`WAITING_FOR_WORKER`

The worker loop handles waiting and execution.

In automated milestone mode, the supervisor automation script may sleep while waiting for worker state changes. It should invoke Codex only when a job is `ready_for_review`, when no active job exists and no human gate is present, or when recovering from an interrupted supervisor run.

The worker loop must pause globally while `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md`, `.ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md`, `.ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md`, or `.ai/supervisor/SUPERVISOR_ACTION_REQUIRED.md` exists. Do not process queued or rejected jobs until the human gate, structural request, human-review action request, or supervisor action request is resolved.

Terminal job states:
- `accepted`: reviewed and integrated or otherwise accepted by the supervisor.
- `superseded`: no longer relevant because a newer plan or structural decision replaced it.
- `cancelled`: stopped by explicit supervisor or human decision.

The worker loop must not retry terminal states. Use `rejected` only when actionable feedback should be retried by the worker.

## Worker preflight protocol

Before invoking Cursor for a queued or rejected job, the worker loop must run deterministic preflight checks and write `.ai/jobs/JNNNN/preflight.attempt-N.log`.

Preflight should:

- verify the isolated worktree is valid and on the expected branch;
- verify `base_sha` is an ancestor of the worktree `HEAD`;
- initialize configured Git submodules by default;
- verify any project-declared required submodule paths listed in `WORKER_REQUIRED_SUBMODULE_PATHS`;
- block before spending an agent attempt if deterministic environment setup fails.

Do not rely on a worker prompt to initialize required build submodules. Deterministic repository setup belongs to the workflow scripts.

Worker lock directories should contain an owner PID. If the worker loop restarts and finds a `running` or `reviewing` job whose lock owner is gone, it may recover the stale state automatically: use `implemented` when a commit and report already exist, otherwise requeue the job for a fresh attempt. Legacy lock directories without owner metadata require explicit opt-in via `WORKER_RECOVER_LEGACY_STALE_LOCKS=1`.

## Review protocol

If a job is `ready_for_review`, inspect:

- `status.json`
- `report.md`
- `worker_handoff.attempt-N.json`
- reviewer reports under `reviews/`, when present
- the worker's `Skill Suggestions` section, if present
- reviewer assessments of skill suggestions, if present
- `diffstat.attempt-N.txt`
- `changed_files.attempt-N.txt`
- `test.attempt-N.log`
- `.ai/commit_docs/JNNNN_attempt-N_*.md`
- `diff.attempt-N.patch`
- the job branch named in `status.json`
- the isolated worktree `.worktrees/JNNNN/`

Worker implementation files are not expected to exist in the main worktree before acceptance. Inspect implementation files with commands such as:

```bash
git -C .worktrees/JNNNN status --short
git -C .worktrees/JNNNN show --stat --oneline HEAD
git -C .worktrees/JNNNN diff --name-only BASE_SHA..HEAD
git -C .worktrees/JNNNN diff BASE_SHA..HEAD -- path
sed -n '1,160p' .worktrees/JNNNN/path/to/file
```

Use `base_sha` from `status.json`, not a moving ref such as `HEAD`, when comparing worker changes. `base_ref` is human-readable context; `base_sha` is the immutable review boundary.

Do not reject or fail review just because a worker-created file is absent from the main worktree before the job is accepted.

Reviewer reports must not be based only on the worker report. Each reviewer should inspect the actual diff comprehensively: every changed file should either be reviewed directly from the patch/worktree or explicitly listed as unreviewed. If a reviewer cannot review the full diff because it is too large, noisy, generated, or unclear, the recommendation should be revise/split or needs-supervisor-judgment, not accept.

Reviewer reports must include a fenced YAML block:

```yaml
diff_coverage:
  full_diff_reviewed: true
  files_reviewed:
    - path/from/changed_files
  unreviewed_files: []
review_decision:
  recommendation: accept
  blocks_acceptance: false
  blocking_reasons: []
```

The supervisor should check reviewer diff coverage and machine-readable decisions before accepting. The worker loop runs `scripts/check_reviewer_coverage.py` against `changed_files.attempt-N.txt` and parses `review_decision` with `scripts/analyze_reviewer_reports.py`; if the reviewer stage fails or either reviewer blocks acceptance, jobs enter `review_failed` or `review_timeout` instead of `ready_for_review`. If reviewers did not inspect the full actual diff, or if the supervisor cannot reasonably review the risky parts of the diff, reject the job with feedback to split it into smaller closed-form jobs or to separate generated/noisy artifacts from implementation. Large jobs should be accepted only when the review record explains how the full changed-file set was covered.

The worker loop keeps raw agent transcripts as audit artifacts only. It extracts
`worker_handoff.attempt-N.json` from the final structured worker report, then
generates `report.md` and commit documentation from canonical workflow facts
plus that structured handoff. Reviewers and the supervisor should not treat
`cursor_final.attempt-N.md` or `cursor_stream.attempt-N.jsonl` as canonical
state.

The worker loop also runs `scripts/check_attempt_consistency.py` before reviewer handoff. If generated reports or commit documentation contradict canonical workflow facts from `status.json`, the attempt commit range, or `test.attempt-N.log`, the job should be blocked before reviewers run. The supervisor should inspect `attempt_consistency.attempt-N.md` and create workflow-maintenance feedback rather than accepting misleading audit records.

After tests, the worker loop records raw and filtered dirty-worktree status. Jobs may declare expected generated files in `.ai/jobs/JNNNN/allowed_artifacts.txt`; undeclared post-test dirty files block the attempt. This prevents tests from silently creating source, build, cache, or generated artifacts after the worker commit.

Accept only if:
- scope is correct
- tests pass or failure is explicitly justified
- scientific assumptions are documented
- implementation matches the design prompt
- no broad unrelated refactor was introduced
- commit history is reviewable
- commit documentation exists
- the worker report matches the actual diff and tests
- reviewer concerns are resolved, converted into rejection feedback, or explicitly waived with rationale
- reviewer reports include comprehensive actual-diff coverage or the supervisor has documented an equivalent comprehensive review

## Workflow evolution protocol

Each worker report should include:

- `Workflow Friction`: missing context, unclear instructions, repeated boilerplate, unavailable helper commands, painful manual steps, or places where a template/checklist/script would have prevented confusion. `None` is a valid answer.
- `Skill Suggestions`: proposed new or updated skills. `None` is a valid answer.

The worker proposes only. The reviewers assess. The Codex supervisor owns all decisions and implementation of workflow changes.

Skills are filesystem instructions, not hidden runtime state. Before dispatch,
review, or supervisor action, make skills visible by including the output of
`python3 scripts/list_skills.py` in the relevant agent prompt. Workers,
reviewers, and Codex should open the listed `SKILL.md` path before using a
skill.

The supervisor may also identify workflow improvements from repeated failure
artifacts even when the worker did not suggest them. Examples include repeated
`attempt_consistency.attempt-N.md` failures, reviewer coverage failures,
timeout patterns, stale commit documentation, or human interventions outside
milestone gates. Treat these as supervisor-originated workflow-evolution
proposals and evaluate them against existing skills, templates, scripts, and
protocols.

When reviewing a job, reviewers should assess:

- whether the reported friction is real and likely to recur;
- whether it is already covered by an existing skill, checklist, template, script, or documentation;
- whether the right response is a ledger note, project doc, template/checklist update, protocol clarification, script fix, project-specific skill, general reusable skill, defer, or reject;
- whether the worker's proposed skill would reduce future duplication without overlapping existing skills.

When reviewing a job, the supervisor should:

1. Read worker workflow friction, worker skill suggestions, and reviewer assessments.
2. Inspect audit artifacts such as `status.json`, `attempt_consistency.attempt-N.md`, reviewer coverage reports, timeout/failure logs, and `feedback.md` for repeated workflow failure modes that the worker may not recognize.
3. Run `python3 scripts/list_skills.py` to list existing project and workflow skills.
4. Check for duplication by comparing name, trigger conditions, and proposed checklist content against existing `skills/*/SKILL.md` files and supervisor protocols/templates.
5. Prefer the smallest effective durable improvement:
   - ledger note only
   - project documentation
   - job/review template update
   - supervisor/worker/reviewer protocol update
   - helper script fix
   - project-specific skill
   - general reusable workflow skill
6. Reject or defer suggestions that are too narrow, already covered, speculative, or better handled as ordinary docs/tests.
7. Decide location:
   - project-specific skills belong in the project repository under `skills/<skill-name>/SKILL.md`.
   - generally reusable scientific-coding workflow skills belong in the AI workflow repository under `external/ai-supervisor-worker-workflow/skills/<skill-name>/SKILL.md`.
8. If creating a skill, keep it concise: YAML frontmatter with `name` and `description`, then when to use it, checklist, output format, and common failure modes.
9. Record nontrivial proposals and decisions in `.ai/supervisor/workflow_improvement_queue.md` and `.ai/supervisor/skill_decisions.md`. Use `python3 scripts/record_workflow_improvement.py` when convenient.
10. Record the decision in `.ai/supervisor/ledger.md`, including created path or rejection/defer rationale.

For general workflow skills, update and commit the workflow submodule repository first, push it when a remote exists, then update the project submodule pointer in the project repository. If pushing is unavailable, leave the general skill as a proposal in the ledger and do not silently create an unpushed dependency.

At milestone gates, the supervisor should include a short Workflow Evolution section summarizing accepted, deferred, and rejected workflow-friction or skill-suggestion decisions since the previous gate. Human approval is required for major structural workflow changes, but routine clarifications and small template/checklist/script fixes may be handled as workflow-maintenance commits.

## Reviewer protocol

When enabled, the worker loop runs two read-only Cursor reviewers after the worker attempt and validation finish:

- reviewer A focuses on scientific/numerical correctness, assumptions, tolerances, edge cases, and validation quality.
- reviewer B focuses on build/code quality, Kokkos/MPI/OpenMP/SYCL portability, memory layout, tests, and maintainability.

Reviewer outputs are stored in `.ai/jobs/JNNNN/reviews/`. A job in `reviewing` is not ready for supervisor action. The supervisor should wait until the job returns to `ready_for_review`, then inspect the worker report and both reviewer reports before accepting or rejecting.

If a reviewer times out or exits nonzero, the worker loop may retry the reviewer according to its configured relaunch limit. If failures remain, the job state becomes `review_timeout` or `review_failed`. The supervisor should inspect reviewer logs and decide whether to rerun reviewers, reject with worker feedback, mark the job terminal, or open a human gate.

## Agent metrics protocol

Each AI agent invocation should produce a compact metrics record for workflow evaluation and paper reproducibility. Worker and reviewer Cursor records live next to the job artifacts, while supervisor records live under `.ai/metrics/supervisor/`. All records are appended to `.ai/metrics/runs.jsonl`.

Metrics should include role, model, job id or supervisor run id, attempt when applicable, start and finish timestamps, wall time, API duration when available, exit code, token counts when available, and paths to raw logs/streams. Treat the metrics as audit records; do not use them to decide scientific correctness.

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
- run `python3 scripts/integrate_job.py JNNNN` before integration when available; apply with `python3 scripts/integrate_job.py JNNNN --apply` or an equivalent explicit Git command only after the guard passes

If the main worktree has unrelated uncommitted changes that prevent integration, accept/reject the job decision in `status.json`, record the integration blocker in the ledger, create `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md`, and do not create the next job until the blocker is resolved.

## Post-milestone pruning protocol

After a human milestone review is approved, run the accepted-job pruning helper for that approved review record. The helper removes only accepted job worktrees and local worker branches listed in the approved milestone review. Preserve all `.ai/jobs/`, `.ai/commit_docs/`, review records, logs, reports, and patches. Do not prune queued, running, rejected, blocked, or ready-for-review jobs.

## Workflow record commit protocol

Keep `.ai` audit records reviewable but separate from implementation commits. After accepting, rejecting, dispatching, or opening/archiving a human milestone gate, commit workflow records with `python3 scripts/commit_workflow_records.py --message "workflow: record supervisor state"` or a more specific workflow message. The helper stages `.ai` job records, commit documentation, `.ai/supervisor/*.md` supervisor records, human-review records, reusable skills, and selected workflow docs. It excludes `.ai/supervisor/design_prompt.md` unless called with `--include-design-prompt`.

## Major structural change protocol

At a human milestone gate, a reviewer may request a major structural change that supersedes the normal checklist review. Treat this as an architecture/roadmap revision, not as approval of the milestone and not as a normal failed checklist item. Archive the gate, record the request, and create `.ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md` for the supervisor.

Only the Codex supervisor may update `.ai/supervisor/roadmap.md`, `.ai/supervisor/project_brief.md`, `.ai/supervisor/ledger.md`, build/dependency policy, or future job sequencing in response to a structural change request. Do not dispatch a Cursor worker job to revise the roadmap or milestone plan. Workers may suggest plan changes in reports, but must not directly own supervisor planning files unless the human explicitly overrides this policy.

When `.ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md` exists, the supervisor should:
- read the archived gate, human review record, and structural request;
- update the roadmap, project brief, ledger, build/dependency policy, and future job sequencing itself;
- create or update `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md` with a summary of the revised milestones, what changed, why it changed, the proposed next milestone, and a `## Human Review To-Do List` checklist;
- archive or remove `.ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md` only after the revised human gate exists;
- commit workflow records;
- stop without creating a worker job.

If an older worker-created structural revision job exists, treat its report as advisory input only. Do not integrate worker-owned edits to roadmap, project brief, ledger, or future milestone sequencing merely because that job completed. The supervisor should make the final planning edits itself and may reject the worker job as superseded by the supervisor-owned structural protocol.

After creating the structural revision human gate, do not dispatch the next implementation job. Stop at the new human gate until the revised plan is approved. If the supervisor loop was launched with `SUPERVISOR_PUSH_AFTER_STRUCTURAL_GATE=1`, push the supervisor-owned structural revision and review gate to the configured remote; if push fails, record the failure in the ledger and keep the gate in place.

## Human review action protocol

At a human milestone gate, ordinary failed checklist items must pass through the Codex supervisor before Cursor receives work. Archive the gate, record the review, and create `.ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md`.

When `.ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md` exists, the supervisor should:
- read the archived gate, human review record, and action request;
- classify each failed item as implementation, test/validation, documentation, supervisor-owned planning/scope, or human clarification;
- create exactly one small worker job only when the next action is clear and implementation/test/doc scoped;
- split broad concerns into a sequence and dispatch only the first small closed-form job;
- update supervisor-owned planning records itself if the concern changes roadmap, scope, milestones, or scientific acceptance criteria;
- open a new human gate when the concern needs clarification or revised plan approval;
- archive or remove `.ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md` only after a worker job or human gate exists;
- commit workflow records and stop with `WAITING_FOR_WORKER` if a job is queued.

## Supervisor action protocol

Operational supervisor failures should not automatically become human milestone gates. When `.ai/supervisor/SUPERVISOR_ACTION_REQUIRED.md` exists, the Codex supervisor should inspect the referenced logs, repair the state if safe, rerun reviewer or integration steps as appropriate, update events and ledger records, then archive or remove the request. Open `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md` only when there is a real milestone, scope, architecture, or scientific decision the supervisor cannot resolve.

## Rejection protocol

If rejected:
- write concise actionable feedback to `feedback.md`
- update job status to `rejected`
- explain exactly what must change
- avoid rewriting the entire task unless necessary

If the job should not be retried, set it to `superseded` or `cancelled` instead of `rejected`.

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

Supervisor planning files are supervisor-owned. Cursor workers should not be assigned jobs whose objective is to edit `.ai/supervisor/roadmap.md`, `.ai/supervisor/project_brief.md`, `.ai/supervisor/ledger.md`, or milestone sequencing. If a worker sees that such a change is needed, it should report a suggestion for the supervisor instead of editing those files.

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
