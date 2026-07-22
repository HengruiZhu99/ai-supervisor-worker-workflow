# PROGRESS.jsonl event schema

Use one compact JSON object per line. The ledger is append-only and should record meaningful checkpoint transitions, not every shell command.

## Required fields

```json
{
  "schema_version": 1,
  "run_id": "stable-run-id",
  "seq": 7,
  "timestamp_utc": "2026-07-18T12:34:56+00:00",
  "event": "checkpoint",
  "milestone": "M2",
  "milestone_state_before": "IMPLEMENTING",
  "milestone_state_after": "FOCUSED_GREEN",
  "role": "builder",
  "hypothesis": "The interface flux sign is the source of the parity error.",
  "bounded_action": "Correct the sign at the single interface assembly point.",
  "commands": [
    {
      "command": "ctest -R interface_flux",
      "exit_code": 0,
      "result": "12/12 passed",
      "evidence": "docs/codex/goal-x/evidence/m2-interface-flux.txt"
    }
  ],
  "changed_files": ["src/flux.cpp", "tests/test_flux.cpp"],
  "gate_delta": ["CT3: fail -> pass"],
  "progress_measure": "max parity error 2.1e-5 -> 4.8e-13",
  "failure_signature": null,
  "same_failure_attempts": 0,
  "no_progress_checkpoints": 0,
  "git_head": "<SHA>",
  "next_action": "Run the milestone regression set and request an independent audit.",
  "next_action_verify": "ctest -R 'interface|restart'"
}
```

## Event values

Use one of:

- `run_initialized`
- `red_established`
- `checkpoint`
- `audit_requested`
- `audit_result`
- `milestone_passed`
- `milestone_reopened`
- `blocked`
- `handoff_created`
- `resume_verified`
- `contract_change_authorized`
- `run_completed`

## Rules

- `seq` is strictly increasing by one within a run.
- A checkpoint must name one active milestone and one bounded action.
- `gate_delta` must be measurable; an empty list means the event cannot reset the no-progress counter.
- Normalize repeated failures into a stable signature such as test ID + exception/error class + key message. Do not use a full timestamped log as the signature.
- Record exact evidence paths instead of pasting large output into the ledger.
- A milestone cannot move to `PASSED` without an `audit_result` event from a fresh or explicitly independent verification pass.
- A `milestone_reopened` event must name the regression or contract evidence that invalidated the earlier pass.
- Do not write secrets or sensitive data.
