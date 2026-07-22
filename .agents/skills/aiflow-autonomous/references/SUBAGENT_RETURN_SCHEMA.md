# Direct-child result schema

```yaml
schema_version: 1
project_id: ...
checkout_id: ...
run_id: ...
task_id: ...
agent_role: ...
status: completed | blocked | failed
summary: ...
findings: []
changed_files: []
commands_run: []
tests_and_results: []
acceptance_ids_supported: []
evidence_paths: []
contract_impact: none | clarification_needed | conflict
residual_risks: []
blocker:
  kind: none | contract | environment | state | acceptance | permissions
  detail: ""
recommended_next_action: ...
```

A child never declares its own work accepted and never launches another child.
