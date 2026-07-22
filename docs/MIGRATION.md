# Migration guide

## Canonical commands

| Legacy surface | Replacement | Support deadline |
|---|---|---|
| `scripts/worker_loop.sh` | `aiflow run resume` | 2027-01-31 |
| `scripts/supervisor_loop.sh` | `aiflow controller run` | 2027-01-31 |
| `scripts/modulator_loop.sh` | deterministic controller/watchdog | 2027-01-31 |
| `scripts/integrate_job.py` | `aiflow integrate` | 2027-01-31 |
| `scripts/workflow_gui.py` | `aiflow gui` | 2027-01-31 |
| `install.sh TARGET` | `aiflow --project-root TARGET project init` | 2027-01-31 |

Shims are finite launchers: minimal argument translation, warning, canonical invocation,
and exit-code propagation. Live usage counts and compatibility tests are tracked in
`.aiflow/deprecations.toml`.

## Existing projects

1. Keep user changes intact and make a normal backup/commit according to project policy.
2. Install the runtime once.
3. Run `aiflow project init --profile solo` in the explicit Git root.
4. Move project-specific build/test/environment arrays into `.aiflow/project.toml` and
   site settings into `.aiflow/site.toml`.
5. Run project/skill/quality verification.
6. Upgrade profiles transactionally; retain the returned rollback transaction ID.

Uninstall removes only unchanged hash-owned managed files. Modified files are preserved
and reported. The runtime, live Git-common-dir state, and user files are never recursively
deleted by project uninstall.

## Cursor compatibility

Codex is the active default. The Cursor wrapper remains registered for explicit opt-in;
compatibility metadata is not an active launch default. Project `.codex/agents` use the
current native TOML schema and depth-one guard.
