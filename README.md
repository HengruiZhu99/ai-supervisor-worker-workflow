# AI Supervisor/Worker Workflow Package

This repository contains a reusable filesystem-based AI supervisor/worker workflow for scientific coding projects.

It provides:
- Codex supervisor protocol and review templates
- Cursor worker loop
- optional Codex supervisor automation loop
- local browser dashboard for jobs, worker/supervisor state, worktrees, roadmap, and project status
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
python3 -m py_compile scripts/create_job.py scripts/update_job_status.py scripts/summarize_jobs.py scripts/create_commit_doc.py scripts/human_milestone_review.py scripts/workflow_gui.py
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
- supervisor launch/stop controls with Codex model, reasoning effort, poll interval, and verbose heartbeat options
- job status and logs
- expandable milestone criteria
- bounded live worker/supervisor loop log panes
- project worktree and expandable file-tree views
- click-to-open files through the system default opener on Ubuntu
- an interactive human milestone review checklist that can create a revision job from failed review items

The log panes show the last 10000 lines by default. To change that display limit:

```bash
AI_WORKFLOW_GUI_LOG_LINES=2000 python3 scripts/workflow_gui.py
```
