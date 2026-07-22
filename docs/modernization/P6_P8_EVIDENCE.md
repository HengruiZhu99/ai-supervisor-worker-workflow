# P6-P8 Evidence: Quality, Native Agents, Finite Execution, and Integration

Date: 2026-07-22

## P6 — quality, deprecation, and compatibility migration

- `aiflow quality baseline|check` measures file/function logical size, AST complexity,
  oversized no-growth, tiny forwarders, core-to-compat imports, expiring exceptions,
  deprecation completeness/expiry, and actual remaining executable call-site counts.
- Default hard limits match the accepted contract. New modular source is below every
  file/function/complexity hard limit.
- The worker, supervisor, and modulator shell implementations are now 24, 22, and 22
  physical lines. They are finite warning shims over `aiflow controller run`; none has a
  permanent loop or unbounded worker/test timeout.
- The deprecation registry names replacements, owner, compatibility tests, live usage
  counts, removal version, and 2027-01-31 deadline. A finite support policy is documented
  in `docs/compatibility.md`.

## P7 — current Codex custom agents

Nine narrow project agents are installed under `.codex/agents/`:

```text
task-router                 gpt-5.6-luna   read-only
codebase-mapper             gpt-5.6-terra  read-only
docs-researcher             gpt-5.6-terra  read-only
test-architect              gpt-5.6-sol    read-only
implementation-worker       gpt-5.6-sol    workspace-write
scientific-reviewer         gpt-5.6-sol    read-only
engineering-reviewer        gpt-5.6-sol    read-only
ui-auditor                  gpt-5.6-terra  read-only
release-auditor             gpt-5.6-sol    read-only
```

Every child disables `[agents]`, forbids subagents and recursive autonomous invocation,
has explicit approval/sandbox settings, and cannot write canonical state. Orchestrated
start rejects a missing or unrestricted parent permission preflight. Child result
validation rejects identity mismatch and recursive delegation. Consensus remains off by
default. Orchestrated/full profiles hash-lock all nine agent files.

## P8 — one finite engine and two-phase integration

- `aiflow run start|list|status|resume|stop` provides durable Solo and orchestrated run
  lifecycle. Resume has finite wall/task/attempt/idle/agent-call budgets.
- The deterministic watchdog covers process death, lease/heartbeat, recovery, disk,
  inodes, no-progress, and timeout. It makes no idle model calls and diagnoses one changed
  actionable signature at most once.
- State schema 0 migrates transactionally to schema 1 with a retained backup; current
  migration is idempotent. Corrupt snapshots rebuild from checksum-chained replayable
  events with retained pre-repair evidence.
- Review findings have stable IDs, severity, evidence, acceptance impact, and resolution.
  One revision, one root-cause review, then block prevents reviewer ping-pong.
- Integration first applies the candidate in a temporary detached worktree, then runs
  focused, regression, and quality gates, checks target-HEAD CAS, and only then applies
  merge or cherry-pick to the clean target. Pre-apply failures preserve the target.
- The legacy integrator is a 112-line shim over the same package transaction.

## Fresh executable evidence

```text
unit suite                                      55 passed
original RED regression suite                  24 passed
disposable Git integration matrix               5 passed
AthenaK-like C++/CMake Solo RED→GREEN flow       1 passed
legacy script suite                             85 passed
aiflow quality check                            ok, 114 files
aiflow project verify                           ok, no drift
```

The disposable integration matrix covers merge, cherry-pick, duplicate integration,
dirty target, conflict, focused failure, regression failure, quality failure, target
movement, successful apply, and user interruption.

## Acceptance delta

- Closed: `AC-PERM-002`, `AC-BACKEND-002`, `AC-ID-005`.
- Closed: `AC-STATE-002`.
- Closed: `AC-SOLO-001`, `AC-SOLO-003`, `AC-AUTO-001`.
- Closed: `AC-EXEC-001`, `AC-EXEC-002`.
- Closed: `AC-QUALITY-001`, `AC-DEPR-001`, `AC-INTEGRATE-001`.
- Partial: `AC-MIGRATE-001` awaits the modular GUI/API replacement.
- Partial: `AC-STATE-003` awaits GUI/API convergence on the controller mutation path.
