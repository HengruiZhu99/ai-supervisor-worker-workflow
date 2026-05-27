# Detailed Design Prompt

Paste the full detailed scientific software design prompt here.

This file is the authoritative project specification for the AI supervisor/worker workflow.

The Codex supervisor should:
- Read this file when creating the roadmap.
- Extract milestones and acceptance criteria.
- Dispatch small worker jobs based on this design.
- Include only the relevant subset of this design in each worker task.

The Cursor worker should not need to read the entire design prompt unless a job explicitly asks for it.

