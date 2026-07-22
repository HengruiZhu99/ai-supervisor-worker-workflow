# AIFLOW v2 acceptance ledger

These stable IDs translate the accepted design and failure catalog into executable
closure units. An ID closes only with retained command/result evidence; task count,
labels, prose, or accepted commits alone never close it.

## Permissions and backends

- `AC-PERM-001`: every Codex role has explicit approval and sandbox policy; no read-only
  role emits `danger-full-access` or a bypass flag.
- `AC-PERM-002`: orchestrated mode refuses an unrestricted parent permission profile and
  validates effective child filesystem behavior.
- `AC-BACKEND-001`: Codex is the default wrapper for worker, reviewer, supervisor,
  modulator, architect/chat, and panels; Cursor remains explicit compatibility opt-in.
- `AC-BACKEND-002`: deterministic style/quality checks make zero model calls; active
  role defaults use the current GPT-5.6 Sol/Terra/Luna family according to workload,
  with explicit per-role override tests and no blind universal replacement.

## Identity and multi-project isolation

- `AC-ID-001`: logical project, checkout, worktree, and run IDs are generated, stored in
  canonical locations, and carried by applicable artifacts/events/requests.
- `AC-ID-002`: inherited `AIFLOW_*` variables cannot redirect project resolution or a
  child process.
- `AC-ID-003`: two projects, two clones, and linked worktrees receive isolated state,
  runtime, cache, process, API, and UI namespaces.
- `AC-ID-004`: copied checkout-ID, thread/cwd mismatch, shared-home host ambiguity, and
  stale/wrong-checkout mutation fail closed.
- `AC-ID-005`: stop/clean operations for one checkout cannot affect another.

## State and progress

- `AC-STATE-001`: one controller lease owns canonical state; stale revision mutations and
  a second controller claim are rejected.
- `AC-STATE-002`: intents, atomic snapshots, checksums, event sequencing, migrations, and
  repair produce deterministic crash recovery.
- `AC-STATE-003`: workers/reviewers write only validated inbox/evidence results; GUI and
  compatibility shims mutate through the same controller API.
- `AC-PROGRESS-001`: acceptance IDs and retained executable evidence are authoritative;
  fake delivery metadata and milestone closure by job count are rejected.
- `AC-PROGRESS-002`: enabler debt is tied to one named target and cannot be reset by an
  area label or another enabler.
- `AC-PROGRESS-003`: two accepted no-delta checkpoints replan once then block; research
  and planning are not implementation jobs; housekeeping cannot preempt ready delivery.

## Solo and orchestrated execution

- `AC-SOLO-001`: start/status/resume/stop implement a finite one-agent, one-task,
  no-subagent solo lane with durable resume and cold self-review.
- `AC-SOLO-002`: feature, bug, refactor, test/numerical, performance, and portability
  cycles retain discriminating evidence and bounded retries/questions.
- `AC-SOLO-003`: an AthenaK-like existing C++/CMake fixture passes the solo acceptance
  flow; automatic orchestration escalation never occurs.
- `AC-AUTO-001`: `$aiflow-autonomous`, current project custom agents, one writer per
  worktree, independent risk-based review, no default consensus, and no recursive child
  tools are installed and validated.
- `AC-EXEC-001`: controller and watchdog have finite wall/task/attempt/idle budgets,
  deterministic idle exit, capped unchanged failures, and zero idle model calls.
- `AC-EXEC-002`: reviewer ping-pong, consensus disagreement, timeouts, and event-triggered
  diagnosis have finite terminal behavior.

## Quality, migration, and integration

- `AC-QUALITY-001`: quality baseline/check enforce file, function, complexity, cohesion,
  dependency, and oversized-file no-growth rules without line-limit gaming.
- `AC-QUALITY-002`: generic core contains no project/user/site/toolchain contamination;
  project commands are argument arrays or named project scripts.
- `AC-DEPR-001`: deprecations have replacement, owner, tests, usage count, version/date,
  and expiry; core cannot import compat or add deprecated calls.
- `AC-MIGRATE-001`: giant legacy loops/GUI become finite thin shims over coherent modules
  with compatibility evidence and a finite support window.
- `AC-INTEGRATE-001`: two-phase merge/cherry-pick integration tests the integrated state,
  uses target-HEAD CAS, rejects duplicates/dirty targets, and leaves the target unchanged
  on every pre-apply failure.

## Installation, GUI, HPC, and release

- `AC-INSTALL-001`: project init/status/verify/upgrade/rollback/uninstall are
  transactional, idempotent, backup-aware, hash-locked, and remove only unchanged
  managed files for all profiles.
- `AC-SKILL-001`: the verified seed skills plus adapted `tdd-solo` and
  `aiflow-autonomous` are canonical under `.agents/skills`; list/validate/doctor/sync
  detect scope collisions and hash drift.
- `AC-GUI-001`: modular optional API/UI defaults to Solo TDD, keeps project/checkout
  identity visible, uses token/origin/revision checks and SSE replay, and runs built
  assets without Node.
- `AC-GUI-002`: isolated two-project, accessibility, responsive, theme, reconnect,
  stale-mutation, log-bound, and console-error acceptance flows pass.
- `AC-HPC-001`: scheduler behavior is fixture-tested and read-only; generic core has no
  cluster paths or scheduler mutation commands.
- `AC-PACKAGE-001`: supported Python CI matrix, backend/frontend/acceptance/security/docs
  checks, standard-library offline artifact, archive audit, and checksums pass without
  publication.
- `AC-HANDOFF-001`: handoff/resume verifies identity, Git state, contract hashes, and
  evidence handles with exact recovery instructions.
- `AC-AUDIT-001`: fresh architecture, security, scientific/TDD, contamination, UI, and
  release audits have no unresolved critical/high finding.

## Terminal rule

The modernization may finish only when every mandatory ID above is closed with fresh
evidence, or when one documented terminal blocker from the upgrade contract is reached.
