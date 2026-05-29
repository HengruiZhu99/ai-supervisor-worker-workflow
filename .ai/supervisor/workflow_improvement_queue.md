# Workflow Improvement Queue

Reviewed proposals for evolving the AI supervisor/worker workflow.

Workers and reviewers may suggest improvements, but the Codex supervisor owns decisions and implementation. Use this file for durable proposals that are more important than a one-line ledger note.

## Entry Format

Each entry should include:

- source job/reviewer/human input
- category: skill, template, script, protocol, checklist, docs, ledger, or other
- scope: project, general, both, or unknown
- rationale
- proposed change
- supervisor decision
- status: proposed, accepted, created, updated, deferred, or rejected

Use this helper when convenient:

```bash
python3 scripts/record_workflow_improvement.py \
  --source job:JNNNN \
  --category skill \
  --scope project \
  --title "Short title" \
  --rationale "Why this would prevent repeated work" \
  --proposed-change "What should change"
```
