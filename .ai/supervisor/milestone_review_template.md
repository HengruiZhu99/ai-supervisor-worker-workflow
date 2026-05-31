# Human Milestone Review

## Milestone

## Status

Choose one:
- complete
- blocked
- needs scope decision

## Summary

## Accepted jobs

## Rejected or retried jobs

## Commits and commit documentation

## Tests and validation

## Scientific assumptions

## Known limitations

## Risks requiring human decision

## Workflow evolution

Summarize worker-reported friction, reviewer assessments, skill suggestions, and supervisor decisions since the previous milestone gate.

## Recommended next milestone

## Human Review To-Do List

- [ ] Milestone summary is accurate.
- [ ] Accepted jobs and commits are reviewable.
- [ ] Tests and validation are acceptable.
- [ ] Scientific assumptions, risks, and limitations are acceptable.
- [ ] Workflow evolution decisions are acceptable.
- [ ] Recommended next milestone is acceptable.

## Human Review Instructions

Run:

```bash
python3 scripts/human_milestone_review.py
```

Answer `yes` or `no` for every checklist item. If any item is `no`, enter comments when prompted. The script will still ask about the remaining items, then create a supervisor action request. The supervisor will decide whether to create one small worker revision job, split the concerns, update plans, or ask for clarification.

If every checklist item is approved, you may add an optional approval comment for the durable review record.
