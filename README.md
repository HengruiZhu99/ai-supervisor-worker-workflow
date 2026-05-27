# AI Supervisor/Worker Workflow Package

This repository contains a reusable filesystem-based AI supervisor/worker workflow for scientific coding projects.

It provides:
- Codex supervisor protocol and review templates
- Cursor worker loop
- optional Codex supervisor automation loop
- local browser dashboard for jobs, worker/supervisor state, worktrees, roadmap, and project status
- automatic pruning of accepted job worktrees and local branches after human milestone approval
- separate workflow-state commits for `.ai` audit records after supervisor or human-review updates
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
python3 -m py_compile scripts/create_job.py scripts/update_job_status.py scripts/summarize_jobs.py scripts/create_commit_doc.py scripts/commit_workflow_records.py scripts/human_milestone_review.py scripts/prune_accepted_job_refs.py scripts/workflow_gui.py
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

The dashboard includes:
- worker launch/stop controls with Cursor model, timeout, and force options
- reviewer controls for two read-only Cursor reviewer passes after each worker attempt
- supervisor launch/stop controls with Codex model, reasoning effort, poll interval, and verbose heartbeat options
- job status and logs
- reviewer report display for the latest reviewed or actively reviewing job
- expandable milestone criteria
- bounded live worker/supervisor loop log panes
- project worktree and expandable file-tree views
- click-to-open files through the system default opener on Ubuntu
- an interactive human milestone review checklist that can create a revision job from failed review items

If the human review marks a major structural change, the workflow creates a planning revision job instead of continuing implementation. That job must update the milestone plan and create a fresh `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md` gate summarizing what changed and what the next small worker jobs should be. The supervisor stops at that second gate until the revised plan is approved.

When a human milestone review is approved, the workflow removes accepted job worktrees and local `ai/JNNNN` branches listed in that approved review record. Job records, logs, reports, patches, and commit documentation under `.ai/` are preserved. Active, rejected, blocked, and ready-for-review jobs are not pruned.

To ask the supervisor loop to push the main branch after accepting a structural planning revision and opening the follow-up human review gate, launch it with:

```bash
SUPERVISOR_PUSH_AFTER_STRUCTURAL_GATE=1 ./scripts/supervisor_loop.sh
```

The worker loop runs two read-only Cursor reviewers by default after the worker finishes and before the supervisor sees `ready_for_review`:

```bash
CURSOR_REVIEWER_A_MODEL=claude-opus-4-7-thinking-high \
CURSOR_REVIEWER_B_MODEL=gpt-5.3-codex-high \
./scripts/worker_loop.sh
```

Reviewer A is tuned for scientific/numerical review. Reviewer B is tuned for build, Kokkos/backend portability, tests, and maintainability. Set `CURSOR_REVIEWERS_ENABLED=0` to disable this stage.

The log panes show the last 10000 lines by default. To change that display limit:

```bash
AI_WORKFLOW_GUI_LOG_LINES=2000 python3 scripts/workflow_gui.py
```
