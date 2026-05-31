# AI Supervisor/Worker Workflow Package

This repository contains a reusable filesystem-based AI supervisor/worker workflow for scientific coding projects.

It provides:
- Codex supervisor protocol and review templates
- Cursor worker loop
- optional Codex supervisor automation loop
- local browser dashboard for jobs, worker/supervisor state, worktrees, roadmap, and project status
- automatic pruning of accepted job worktrees and local branches after human milestone approval
- separate workflow-state commits for `.ai` audit records after supervisor or human-review updates
- structured workflow event records for failures, reviewer blocks, and human interventions
- guarded job integration from immutable `base_sha` boundaries
- pluggable agent wrapper registry for worker, reviewer, supervisor, and chat roles
- reusable scientific coding skills
- dependency-free Python helper scripts
- generic `.ai/` templates

It intentionally excludes project-specific state:
- real design prompts
- filled project briefs
- customized roadmaps
- ledgers with scientific assumptions
- worker jobs
- worker logs, diffs, reports, and commit docs

## Install into a Project

From a target Git repository:

```bash
/path/to/ai-supervisor-worker-workflow/install.sh .
```

The installer refuses to overwrite existing files by default. To overwrite installed workflow files:

```bash
AI_WORKFLOW_OVERWRITE=1 /path/to/ai-supervisor-worker-workflow/install.sh .
```

After installation, read:

```text
.ai/README.md
```

## Use as a Submodule

From a project repository:

```bash
git submodule add /path/to/ai-supervisor-worker-workflow external/ai-supervisor-worker-workflow
git commit -m "workflow: add ai workflow submodule"
```

Then install or update the workflow files from the submodule:

```bash
external/ai-supervisor-worker-workflow/install.sh .
```

## Validation

```bash
bash -n scripts/worker_loop.sh
bash -n scripts/supervisor_loop.sh
python3 -m py_compile scripts/agent_wrapper.py scripts/create_job.py scripts/update_job_status.py scripts/summarize_jobs.py scripts/create_commit_doc.py scripts/commit_workflow_records.py scripts/check_reviewer_coverage.py scripts/analyze_reviewer_reports.py scripts/filter_allowed_artifacts.py scripts/integrate_job.py scripts/record_workflow_event.py scripts/transition_job.py scripts/human_milestone_review.py scripts/list_skills.py scripts/prune_accepted_job_refs.py scripts/workflow_gui.py
```

## Dashboard

From a project repository with the workflow installed:

```bash
python3 scripts/workflow_gui.py
```

Then open:

```text
http://127.0.0.1:8765/
```

The first launch stores the selected dashboard port in
`.ai/runtime/workflow_gui_port.json`.  Later launches from the same project reuse
that port automatically.  If the stored/default port is already in use by
another project, the dashboard selects the next available port and updates that
project-local file.  Pass `--port N` only when you want to override the stored
port manually.

The dashboard includes:
- worker launch/stop controls with wrapper, model, timeout, and force options
- wrapper and model selectors for worker, reviewer A, reviewer B, and supervisor agents
- reviewer controls for two read-only reviewer passes after each worker attempt
- supervisor launch/stop controls with wrapper, model, reasoning effort, poll interval, and verbose heartbeat options
- job status and logs
- reviewer report display for the latest reviewed or actively reviewing job
- expandable milestone criteria
- bounded live worker/supervisor loop log panes
- project worktree and expandable file-tree views
- click-to-open files through the system default opener on Ubuntu
- an always-available Workflow Chat in Project Overview for workflow questions, current-run diagnosis, and explicitly enabled workflow edits
- an interactive human milestone review checklist that routes failed review items back through the supervisor
- a read-only "Ask Supervisor" chat inside the human milestone review panel for questions before submitting the checklist

Loops launched from the dashboard are wrapped with a small crash relaunch guard. The default is three process-level restarts; adjust with `AI_WORKFLOW_LOOP_MAX_RESTARTS` and `AI_WORKFLOW_LOOP_RESTART_DELAY`.
After a successful human-review submission through the dashboard or `scripts/human_milestone_review.py`, the workflow automatically starts the supervisor and worker loops if either is offline. It also pushes the current branch to `origin` by default after recording the human review. Disable that push with `AI_WORKFLOW_PUSH_AFTER_HUMAN_REVIEW=0`, or choose a different target with `AI_WORKFLOW_PUSH_REMOTE` and `AI_WORKFLOW_PUSH_BRANCH`.

Workflow Chat defaults to read-only guidance. To let the chat agent edit workflow files, enable "Allow this chat agent to edit workflow files" before sending the request. Edit mode is intended for workflow maintenance, not scientific implementation jobs; it should not run Cursor, start loops, or modify active job artifacts unless explicitly requested.

If the human review marks a major structural change, implementation pauses and `.ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md` is created. The Codex supervisor, not a worker job, updates the milestone plan and creates a fresh `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md` gate summarizing what changed and what the next small worker jobs should be. The supervisor stops at that second gate until the revised plan is approved.

If ordinary checklist items fail, implementation also pauses and `.ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md` is created. The supervisor reads the failed review items first, then creates a small worker revision job, splits the concerns, updates planning records, or asks for clarification.

When a human milestone review is approved, the workflow removes accepted job worktrees and local `ai/JNNNN` branches listed in that approved review record. Job records, logs, reports, patches, and commit documentation under `.ai/` are preserved. Active, rejected, blocked, and ready-for-review jobs are not pruned.

To ask the supervisor loop to push the main branch after accepting a structural planning revision and opening the follow-up human review gate, launch it with:

```bash
SUPERVISOR_PUSH_AFTER_STRUCTURAL_GATE=1 ./scripts/supervisor_loop.sh
```

The worker loop runs two read-only Cursor reviewers in parallel by default after the worker finishes and before the supervisor sees `ready_for_review`:

```bash
CURSOR_REVIEWER_A_MODEL=claude-opus-4-7-thinking-high \
CURSOR_REVIEWER_B_MODEL=gpt-5.3-codex-high \
./scripts/worker_loop.sh
```

Reviewer A is tuned for scientific/numerical review. Reviewer B is tuned for build, Kokkos/backend portability, tests, and maintainability. Set `CURSOR_REVIEWERS_ENABLED=0` to disable this stage.

Reviewer reports include a machine-checkable `diff_coverage` YAML block. The worker loop writes `changed_files.attempt-N.txt` from `base_sha..HEAD` and runs `scripts/check_reviewer_coverage.py`; reviewer failure leaves the job in `review_failed` or `review_timeout` for supervisor action.

Reviewer reports also include a machine-checkable `review_decision` YAML block. The worker loop parses this with `scripts/analyze_reviewer_reports.py`; if either reviewer blocks acceptance, the job stays in `review_failed` for supervisor decision instead of silently becoming ready.

Raw worker transcripts are audit artifacts only. After the worker wrapper exits,
the loop extracts `worker_handoff.attempt-N.json` from the final structured
worker report, then generates `report.md` and commit documentation from
canonical workflow facts plus that structured handoff. Reviewers and the
supervisor should use `status.json`, Git history, test logs, changed-file lists,
diff artifacts, commit docs, and the generated `report.md` as review inputs;
`cursor_final.attempt-N.md` and `cursor_stream.attempt-N.jsonl` are for debugging
inconsistencies, not for canonical state.

Worker validation can be bounded with `TEST_TIMEOUT`. After tests, the worker loop records both raw and filtered dirty-worktree status. A job may declare expected generated artifacts in `.ai/jobs/JNNNN/allowed_artifacts.txt`; all other post-test dirty files block the attempt.

Before integrating an accepted job, the supervisor can run:

```bash
python3 scripts/integrate_job.py JNNNN
python3 scripts/integrate_job.py JNNNN --apply
```

The guard checks immutable `base_sha`, reviewer completion, tests, post-test cleanliness, and attempt consistency before merging the worker branch.

The worker loop normalizes common accidental Codex-style Cursor model ids, for example `gpt-5.5` to `gpt-5.5-high`, before invoking `cursor-agent`. If Cursor returns nonzero after emitting `[system success]`, tests pass, and the post-test worktree is clean, the attempt proceeds to reviewer review while recording the nonzero exit in `status.json`.

Agent wrappers are isolated under `agent_wrappers/<wrapper-id>/wrapper.json` and invoked through `scripts/agent_wrapper.py`. List available wrappers with:

```bash
python3 scripts/agent_wrapper.py list --json
```

The built-in wrappers are role-neutral: `cursor-agent` is recommended for worker/reviewer roles, and `codex` is recommended for supervisor/chat roles, but the dashboard can select either wrapper for any role. A future wrapper such as Claude Code can be added by creating a new wrapper directory with `wrapper.json` and either adding a built-in runner to `scripts/agent_wrapper.py` or providing a `command` template in the JSON file.

If an older workflow leaves a completed attempt in a blocked state before reviewers run, set the job state to `implemented`; the worker loop will run only the reviewer stage for the existing `base_sha..commit` attempt and then move the job to `ready_for_review`, `review_failed`, or `review_timeout`.

Worker reports should include a `Skill Suggestions` section. Reviewers assess those suggestions, and the supervisor checks them against existing skills with:

```bash
python3 scripts/list_skills.py
```

Project-specific skills belong in the project `skills/` directory. Generally reusable scientific-coding workflow skills belong in this workflow package's `skills/` directory.

Supervisor, worker, and reviewer prompts include the skill index generated by
`python3 scripts/list_skills.py`. This makes project skills and reusable
workflow skills visible to both Codex and Cursor; agents still need to open the
listed `SKILL.md` file before applying a skill.

The supervisor may also create or update skills from repeated failure artifacts
even when the worker does not suggest them. For example, repeated
`attempt_consistency.attempt-N.md` failures should trigger the reusable
`attempt-artifact-consistency` skill and, when needed, a script or template fix.

The log panes show the last 10000 lines by default. To change that display limit:

```bash
AI_WORKFLOW_GUI_LOG_LINES=2000 python3 scripts/workflow_gui.py
```
