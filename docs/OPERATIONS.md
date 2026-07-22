# Operations and recovery

## Start and inspect

```bash
aiflow project init --profile solo
aiflow run start --mode solo --objective "bounded outcome" --acceptance-id AC-1
aiflow run status --run-id RUN_ID
```

Runs start paused. Resume uses finite wall/task/attempt/idle/model-call budgets and exits
to a durable terminal reason. An idle controller makes zero model calls.

## Recovery

```bash
aiflow state verify --run-id RUN_ID
aiflow state repair --run-id RUN_ID
aiflow state migrate --run-id RUN_ID
aiflow run resume --run-id RUN_ID --max-idle 1
```

Verify is non-mutating. Repair replays the checksum event chain and keeps a backup before
replacing inconsistent snapshots. Migration is transactional and idempotent. A controller
lease is runtime-only and must be reclaimed under the PID/host/boot rules.

## Portable handoff

```bash
aiflow run handoff --run-id RUN_ID
aiflow run verify-handoff .aiflow/handoffs/RUN_ID.json
```

The handoff contains no token or raw transcript. It is signed and binds project, checkout,
worktree, run, revision, Git HEAD, contract digest, tasks/evidence, and exact resume
command. Any stale or cross-project value blocks verification.

## GUI

Run one server per checkout. Keep the endpoint/token printed by that invocation together;
tokens are never shared through the hub. Use SSH local forwarding for a remote project
instead of exposing a non-loopback listener.

## HPC

The `hpc` profile installs a site-neutral `.aiflow/site.toml`. Configure the project-owned
environment setup script, modules, and storage roots there. Monitoring accepts only
`squeue` or `qstat` query arrays, caches within the minimum interval, and exposes no
cancel/submit/requeue operation.

No cleanup command removes another checkout's state/runtime/cache. Candidate branches and
failed integration worktrees remain recoverable until explicit retention policy permits
pruning.
