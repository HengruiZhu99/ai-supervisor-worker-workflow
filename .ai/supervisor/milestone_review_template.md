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

## Recommended next milestone

## Human Review To-Do List

- [ ] Milestone summary is accurate.
- [ ] Accepted jobs and commits are reviewable.
- [ ] Tests and validation are acceptable.
- [ ] Scientific assumptions, risks, and limitations are acceptable.
- [ ] Recommended next milestone is acceptable.

## Human Review Instructions

Run:

```bash
python3 scripts/human_milestone_review.py
```

Answer `yes` or `no` for every checklist item. If any item is `no`, enter comments when prompted. The script will still ask about the remaining items, then create one revision worker job covering all failed items.
