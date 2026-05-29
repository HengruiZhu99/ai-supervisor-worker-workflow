# AI Workflow

## Overview

Codex is the supervisor. Cursor is the worker.

`.ai/supervisor/` contains durable high-level state, including the design prompt, project brief, roadmap, ledger, review checklist, and protocols.

`.ai/jobs/` contains worker jobs. Each job lives under `.ai/jobs/JNNNN/` and contains a task, status, reports, logs, diffs, and feedback.

`.ai/commit_docs/` contains documentation for worker commits and attempts.

`.worktrees/` contains isolated implementation worktrees created by the worker loop.

## Basic Usage

### Step 1

Paste the detailed design prompt into:

```text
.ai/supervisor/design_prompt.md
```

### Step 2

Ask Codex:

```text
Read `AGENTS.md`, `.ai/supervisor/supervisor_protocol.md`, and `.ai/supervisor/design_prompt.md`. Extract the project roadmap, update `.ai/supervisor/project_brief.md`, update `.ai/supervisor/roadmap.md`, update `.ai/supervisor/ledger.md`, and create exactly one small first worker job under `.ai/jobs/`. Do not implement the project yourself. If a worker job is queued or running, stop with `WAITING_FOR_WORKER`.
```

### Step 3

Run the worker loop in one terminal or tmux pane:

```bash
chmod +x scripts/worker_loop.sh
CURSOR_MODEL=gpt-5.5-high ./scripts/worker_loop.sh
```

The worker loop defaults to GPT-5.5 High through Cursor's model id:

```bash
CURSOR_MODEL=gpt-5.5-high ./scripts/worker_loop.sh
```

By default, the worker loop also runs two read-only Cursor reviewers in parallel after a successful worker attempt and before the supervisor sees the job as ready for review:

```bash
CURSOR_REVIEWER_A_MODEL=claude-opus-4-7-thinking-high \
CURSOR_REVIEWER_B_MODEL=gpt-5.3-codex-high \
./scripts/worker_loop.sh
```

Reviewer A focuses on scientific/numerical correctness. Reviewer B focuses on code quality, build behavior, Kokkos/backend portability, tests, and maintainability. Set `CURSOR_REVIEWERS_ENABLED=0` to skip reviewer passes.

Reviewers are expected to inspect the actual diff comprehensively. Their reports should include a diff-coverage statement listing changed files reviewed and any paths not reviewed. If a diff is too large to review end to end, reviewers should recommend splitting the job rather than accepting it.

Each reviewer report must include:

```yaml
diff_coverage:
  full_diff_reviewed: true
  files_reviewed:
    - path/from/changed_files
  unreviewed_files: []
```

The worker loop writes `changed_files.attempt-N.txt` from the immutable `base_sha..HEAD` range and checks reviewer coverage before a job becomes ready for supervisor review.

Worker reports should include a `Skill Suggestions` section. Reviewers assess those suggestions, and the supervisor checks existing skills before creating anything:

```bash
python3 scripts/list_skills.py
```

To see the model ids available to your Cursor account:

```bash
cursor-agent models
```

If your local Cursor Agent requires extra flags for unattended command execution, pass them through `CURSOR_AGENT_EXTRA_ARGS`. For example:

```bash
CURSOR_MODEL=gpt-5.5-high CURSOR_AGENT_EXTRA_ARGS="--force" ./scripts/worker_loop.sh
```

Nonzero Cursor worker exits are requeued once by default when the failure is not a timeout and tests did not create dirty files. Adjust with `WORKER_AUTO_RELAUNCH_FAILURE` and `WORKER_MAX_FAILURE_RESUMES`. Reviewer exits are retried with `CURSOR_REVIEWER_MAX_RELAUNCHES`.

The worker loop normalizes common accidental Codex-style Cursor model ids, such as `gpt-5.5` to `gpt-5.5-high`. If Cursor exits nonzero after emitting `[system success]`, tests pass, and the post-test worktree is clean, the attempt is still sent to reviewers while the nonzero Cursor exit remains documented.

For recovery, a completed attempt can be marked `implemented`; the worker loop then runs only reviewers for the existing attempt and moves the job to `ready_for_review`, `review_failed`, or `review_timeout`.

### Step 4

Run the autonomous Codex supervisor loop in another terminal or tmux pane:

```bash
chmod +x scripts/supervisor_loop.sh
./scripts/supervisor_loop.sh
```

The supervisor loop invokes `codex exec` only when action is needed:

- no active worker job exists and the milestone needs the next job
- a job is `ready_for_review`
- a job is `blocked`

It does not ask for human input after every small job. It reviews job reports, tests, diffs, and commit documentation; accepts or rejects jobs; updates the ledger; and dispatches the next small job while the current milestone remains approved.

Jobs store both `base_ref` and immutable `base_sha`. Reviewers and the supervisor should compare `base_sha..HEAD`, because branch names and `HEAD` can move as workflow records are committed.

The supervisor loop defaults to the ChatGPT Codex naming convention for GPT-5.5 High: `CODEX_MODEL=gpt-5.5` with `CODEX_REASONING_EFFORT=high`. Cursor model ids and Codex model ids are not guaranteed to match; Cursor uses `gpt-5.5-high`, while Codex uses `gpt-5.5` plus high reasoning effort.

To choose a Codex-supported model for the supervisor loop:

```bash
CODEX_MODEL=gpt-5.5 CODEX_REASONING_EFFORT=high ./scripts/supervisor_loop.sh
```

To print a heartbeat while the supervisor is waiting:

```bash
SUPERVISOR_VERBOSE=1 SUPERVISOR_POLL_SECONDS=60 ./scripts/supervisor_loop.sh
```

The supervisor retries a crashed `codex exec` once by default. Adjust with `SUPERVISOR_AUTO_RELAUNCH_FAILURE` and `SUPERVISOR_MAX_FAILURE_RELAUNCHES`.

### Step 5

Check jobs any time:

```bash
python3 scripts/summarize_jobs.py
```

Open the local workflow dashboard:

```bash
python3 scripts/workflow_gui.py
```

Then visit:

```text
http://127.0.0.1:8765/
```

The dashboard can launch and stop the worker and supervisor loops, show job/worktree/project status, expand milestone criteria, process human milestone review checklists, and ask workflow-aware Codex chat questions. The Project Overview Workflow Chat is always available and defaults to read-only guidance; enable its edit checkbox only when you want the chat agent to change workflow files. After a successful human-review submission through the dashboard or `scripts/human_milestone_review.py`, the workflow automatically starts the supervisor and worker loops if either is offline.

Loops launched from the dashboard are wrapped with a small crash relaunch guard. The default is three process-level restarts; adjust with `AI_WORKFLOW_LOOP_MAX_RESTARTS` and `AI_WORKFLOW_LOOP_RESTART_DELAY`.

### Step 6

When the current milestone is complete or blocked, the supervisor loop writes:

```bash
.ai/supervisor/HUMAN_REVIEW_REQUIRED.md
```

Review that milestone summary with the interactive checklist command:

```bash
python3 scripts/human_milestone_review.py
```

Answer `yes` or `no` for every review item. If an item fails, enter comments when prompted. The script will still cycle through the rest of the list, archive the gate, record the review, and create `.ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md`. The supervisor then reads the request and decides whether to create a small worker revision job, split the concerns, update planning records, or ask for clarification.

For major architecture, dependency, or roadmap changes, use the dashboard's Major Structural Change box or answer yes to the CLI structural-change prompt. That path supersedes the checklist outcome and creates `.ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md` for the Codex supervisor.

The supervisor owns structural planning. It updates the roadmap and related architecture records itself, then creates a fresh `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md` gate summarizing the revised milestones and proposed next worker jobs. The supervisor should stop there until the revised plan is approved. Cursor workers may suggest roadmap changes in reports, but should not be assigned roadmap, project brief, ledger, or milestone-sequence edits.

If every item passes, the script archives the gate, records approval, and prunes accepted job worktrees and local `ai/JNNNN` branches listed in the approved milestone review. `.ai/jobs/` and `.ai/commit_docs/` records are preserved. Active, rejected, blocked, and ready-for-review jobs are not pruned.

While `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md`, `.ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md`, or `.ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md` exists, the worker loop pauses globally and will not process queued or rejected jobs.

The same approval and pruning behavior is available through the dashboard human review panel.

Manual per-job review is still possible. Stop `scripts/supervisor_loop.sh` and ask Codex to review a `ready_for_review` job if you want to inspect a specific job yourself. If reviewer reports exist under `.ai/jobs/JNNNN/reviews/`, include them in the review.

Workflow record commits are kept separate from implementation commits when possible. The supervisor and human-review helpers use `scripts/commit_workflow_records.py` to commit `.ai` job records, commit documentation, human-review records, ledger updates, and roadmap updates without mixing them into scientific source commits.

## Commit Documentation

Each worker attempt should produce a markdown file under:

```text
.ai/commit_docs/
```

Each file records:

- job id
- attempt
- commit hash
- attempt commit range
- all commits in the attempt
- diff stat
- changed files
- test result
- summary
- known limitations
- follow-up suggestions

## Manual Commands

```bash
bash -n scripts/worker_loop.sh
bash -n scripts/supervisor_loop.sh
python3 -m py_compile scripts/create_job.py scripts/update_job_status.py scripts/summarize_jobs.py scripts/create_commit_doc.py scripts/commit_workflow_records.py scripts/check_reviewer_coverage.py scripts/human_milestone_review.py scripts/list_skills.py scripts/workflow_gui.py
python3 scripts/summarize_jobs.py
```
