# Architecture

## One engine, two modes

`src/aiflow` is the canonical implementation. Solo and orchestrated modes share identity,
state, controller, evidence, quality, recovery, handoff, and integration modules. Mode is
a policy choice, not a separate engine.

```text
CLI / project GUI / compatibility shims
                 |
        named controller commands
                 |
 identity -> RunLifecycle -> revisioned RunStore -> events/evidence
                 |
      finite controller and watchdog
                 |
       review -> integration transaction
```

The GUI never edits state. Workers and reviewers return identity-bound structured results;
only the parent controller ingests them. Integration has its own target-HEAD compare-and-
swap after integrated-state gates.

## Modules

- `identity`: project, checkout, worktree, run, thread, runtime, and cache isolation.
- `state`: signed snapshots, revisions, leases, intents, events, repair, migration,
  lifecycle, and portable handoff.
- `controller`: finite budgets, deterministic idle exit, and event-triggered watchdog.
- `domain`: acceptance progress, evidence contracts, and Solo/orchestrated routing.
- `agents`: depth-one result/review contracts and the offline fake backend.
- `skills`: seed verification, discovery, collision checks, and transactional profiles.
- `quality`: measured limits, no-growth baseline, deprecations, and exceptions.
- `integration`: temporary-worktree merge/cherry-pick transaction.
- `api`: project server, SSE replay, security, static UI, and read-only hub.
- `scheduler`: read-only fixture parsers and rate-limited query construction.
- `release`: zipapp construction, internal manifest, and checksum audit.

## Identity boundary

Logical project ID is stored in `.aiflow/project.toml`. Checkout ID belongs to the Git
common directory. Worktree ID belongs to the worktree Git directory. Run ID selects a
canonical state directory. A mismatch at any layer fails closed.

## Dependency policy

Core has no runtime dependency beyond Python 3.11+. React, TypeScript, esbuild, and
Playwright are build/test dependencies only. No database, Node runtime, scheduler SDK,
daemon, or live model is mandatory for tests.
