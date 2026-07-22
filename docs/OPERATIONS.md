# Operations and recovery

## Start and inspect

```bash
aiflow project init --profile solo
aiflow run start --mode solo --objective "bounded outcome" --acceptance-id AC-1 \
  --allowed-scope src/widget.py --allowed-scope tests/test_widget.py
aiflow run status --run-id RUN_ID
```

First configure `[commands].test_red`, `test_focused`, and `test_regression` in
`.aiflow/project.toml`; for the selected task kind, the pre-change command must be rerun
unchanged by the post-change gates. Intake validates executable scope and command
contracts before creating run state. Runs start paused. Resume uses finite
wall/task/attempt/idle/model-call budgets and exits to a durable terminal reason. An idle
controller makes zero model calls.

For example, a Python project can use:

```toml
[commands]
build = ["python3", "-m", "compileall", "-q", "src"]
test_red = ["python3", "-m", "unittest", "tests.test_widget"]
test_focused = ["python3", "-m", "unittest", "tests.test_widget"]
test_regression = ["python3", "-m", "unittest", "discover", "-s", "tests"]
```

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

Orchestrated integration records a durable transaction before applying the candidate.
It binds the target ref/commit, tested tree, focused/regression/quality evidence, and
transaction identity. Recovery resumes that exact transaction after a crash—even in the
post-CAS/pre-refresh window—rather than guessing from ancestry. A writer worktree remains
available until `task_accepted` is durable. Orphan inbox recovery scans every ready task,
and signed replay is idempotent; conflicting replay fails closed.

## Portable handoff

```bash
aiflow run handoff --run-id RUN_ID
aiflow run verify-handoff .aiflow/handoffs/RUN_ID.json
```

The handoff contains no token or raw transcript. It is signed and binds project, checkout,
worktree, run, revision, Git HEAD, contract digest, tasks/evidence, and exact resume
command. Any stale or cross-project value blocks verification.

## GUI

Run one server per checkout. The command prints the server URL and private endpoint-file
path, never the mutation token. That token lives in the checkout-scoped `ENDPOINT.json`
with `0600` permissions and the file is removed when the server exits. Tokens are never
shared through the hub. Use SSH local forwarding for a remote project; the server will
not bind a non-loopback listener. Healthy SSE performs no snapshot polling. Reconnect
attempts and fallback snapshot polls are finite; after exhaustion the UI stays idle until
an explicit user action or page reload.

## HPC

The `hpc` profile installs a site-neutral `.aiflow/site.toml`. Configure the project-owned
environment setup script, modules, and storage roots there. Monitoring accepts only
`squeue` or `qstat` query arrays, caches within the minimum interval, and exposes no
cancel/submit/requeue operation.

No cleanup command removes another checkout's state/runtime/cache. Integration gate
worktrees are temporary. If a post-apply rollback encounters untracked files, it preserves
them under `.git/aiflow/recovery/` and reports the exact recovery path.
