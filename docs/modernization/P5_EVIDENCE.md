# P5 Evidence: Acceptance-ID Progress and Starvation Breakers

Date: 2026-07-22

## Implemented contract

- Tasks have one typed value class: delivery, validation, enabler, housekeeping, or
  controller-owned read-only research.
- Delivery/validation tasks must name open acceptance IDs. An enabler must name exactly
  one concrete target task; free-text `unlocks_next` is not authoritative.
- Dispatch order is delivery, validation, one necessary named enabler, then bounded
  housekeeping. A ready acceptance task cannot be preempted by housekeeping.
- Accepting an enabler creates debt tied to its target. No area/subsystem rename or
  lateral enabler clears that debt.
- Actual changed artifacts, commands, passing test results, and expected artifact decide
  whether a delivery claim is credible. Metadata carrying a delivery label is rejected.
- Two accepted checkpoints without an acceptance delta emit `NO_ACCEPTANCE_DELTA`, allow
  one controller-owned replan, and then block unless an acceptance-closing task is ready.
- Milestone closure requires an acceptance delta plus fresh end-to-end evidence.
- Deterministic reports expose open/closed acceptance IDs, debt, last delta, ready
  delivery/validation tasks, and remaining housekeeping budget.
- The legacy job gate enforces the same global no-delta rule without allowing subsystem
  changes to reset the counter.

## Fresh evidence

```text
python3 -m unittest tests.unit.test_progress_policy
6 tests passed

python3 -m unittest discover -s tests/regression -p 'test_progress_red.py'
3 tests passed

python3 -m unittest scripts.test_check_job_progress_gate
13 tests passed
```

The full legacy suite remained green at this checkpoint (`85 passed`).

## Acceptance delta

- Closed: `AC-PROGRESS-001`.
- Closed: `AC-PROGRESS-002`.
- Closed: `AC-PROGRESS-003`.
