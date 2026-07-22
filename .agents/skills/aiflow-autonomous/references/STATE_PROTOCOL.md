# State protocol

- Canonical live state is checkout-scoped, not branch-scoped.
- One controller is the sole state/event writer.
- Workers and reviewers write task-scoped inbox/evidence only.
- Every mutation carries the expected state revision.
- Snapshot and event update under one transaction lock and intent record.
- Every artifact includes project, checkout, worktree, and run identity.
- Resume verifies identity, Git state, contract hashes, lease, and load-bearing evidence.
- A handoff is a pointer plus re-verification commands, never an oracle.
