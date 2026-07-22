# P2-P3 Evidence: Identity and State Ownership

Date: 2026-07-22

## Implemented contract

- Project resolution starts from an explicit path and never trusts inherited
  `AIFLOW_*` variables.
- Logical project, checkout, linked-worktree, and run identities are stable and
  stored at Git-common or per-worktree scope as appropriate.
- Runtime leases and cache data live outside the repository and are namespaced by
  project, checkout, and worktree identity.
- The checkout registry rejects a second live path claiming the same checkout ID.
- Thread metadata is validated against the resolved project and checkout.
- Canonical run mutation is controller-only: a current signed lease and expected
  revision are required for every transition.
- Snapshots are atomically replaced; events are sequenced and checksum chained;
  incomplete intents are deterministically rolled forward.
- Worker/reviewer payloads are written to an inbox and cannot directly mutate the
  canonical snapshot.
- The legacy job-status helper now requires compare-and-swap revision input, and
  the legacy worker passes the revision it observed.

## Regression evidence

Commands run from the repository root:

```text
python3 -m unittest discover -s tests/unit -p 'test_*.py'
15 tests passed

python3 -m unittest discover -s tests/regression -p 'test_state_red.py'
3 tests passed

python3 -m unittest discover -s tests/regression -p 'test_permissions_red.py'
3 tests passed

python3 -m unittest discover -s tests/regression -p 'test_contamination_red.py'
2 tests passed

python3 -m unittest discover -s tests/regression -p 'test_backend_defaults_red.py'
4 tests passed

python3 -m unittest discover -s scripts -p 'test_*.py'
85 tests passed
```

## Acceptance delta

- Closed: `AC-ID-001`, `AC-ID-002`, `AC-ID-003`, `AC-ID-004`.
- Closed: `AC-STATE-001`.
- Partial: `AC-ID-005` awaits the lifecycle stop/clean surface.
- Partial: `AC-STATE-002` awaits explicit schema migration and repair commands.
- Partial: `AC-STATE-003` awaits GUI and compatibility-shim convergence on the
  controller API.

## Remaining limitations

- The package CLI is version-only at this checkpoint.
- Controller lifecycle commands, schema migration/repair, and GUI projection are
  intentionally deferred to later bounded phases.
