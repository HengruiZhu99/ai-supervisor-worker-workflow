# P9-P10 evidence: project UI, portable handoff, HPC, and offline artifact

## Acceptance closed

- `AC-STATE-003`: GUI mutations use `RunLifecycle` and revisioned `RunStore`
  transitions; child-result validation remained green.
- `AC-MIGRATE-001`: the 2,843-line legacy GUI server and 2,057 lines of legacy
  frontend were replaced by finite shims; `install.sh` now delegates to the
  transactional profile installer instead of copying a runtime.
- `AC-GUI-001`: isolated loopback server, session token, exact Origin/Host,
  JSON/body bound, revision and checkout CAS, initial snapshot, retained SSE replay,
  Solo-first React/TypeScript UI, and Node-free built assets are executable.
- `AC-GUI-002`: two simultaneous disposable projects retained separate tokens,
  checkout IDs, run stores, and endpoints; stale/wrong mutations failed. Browser
  inspection covered responsive, theme, progressive disclosure, identity, and
  console state.
- `AC-HPC-001`: SLURM/PBS fixture parsers, read-only command allowlists, cached
  minimum polling, and a site-neutral HPC profile pass without scheduler mutation.
- `AC-HANDOFF-001`: portable exports are signed and bound to project, checkout,
  worktree, run, revision, Git HEAD, project-contract digest, task/evidence pointers,
  and an exact resume command; stale/cross-project verification is rejected.

`AC-PACKAGE-001` remains open until P11 CI/release audit, although its standard-library
zipapp, payload manifest, checksum sidecar, offline execution, and offline project-init
tests are already green.

## Tests-first record

The first focused executions failed for missing `aiflow.api.security`, `aiflow.api.sse`,
`aiflow.api.hub`, `aiflow.scheduler.readonly`, `aiflow.release.artifact`, HPC site
configuration, the legacy installer delegation, and `aiflow.state.handoff`. Those RED
contracts were retained as unit/integration tests and turned green in bounded slices.

## Consolidated commands and results

```text
npm --prefix frontend run check                  PASS
npm --prefix frontend run build                  PASS (196.7 KiB built JS)
python3 -m unittest discover -s tests/unit       PASS (69)
python3 -m unittest discover -s tests/regression PASS (24)
python3 -m unittest discover -s tests/integration PASS (12)
python3 -m unittest discover -s tests/acceptance PASS (1)
python3 -m unittest discover -s scripts          PASS (85)
bin/aiflow --project-root . quality check        PASS (137 source files)
bin/aiflow --project-root . project verify       PASS
git diff --check                                 PASS
```

The integration suite includes artifact build/verify/tamper detection, executable
zipapp `--version`, offline Solo project initialization/verification, two project
servers, token isolation, stale and cross-checkout mutations, read-only hub behavior,
static asset serving, and legacy install delegation.

## Real-browser audit

The maintained built assets were served with:

```text
bin/aiflow --project-root . gui --no-open --port 8877
```

The in-app browser's Playwright interface verified:

- accessible banner, main, fieldset/radio, labels, status regions, skip link, and
  buttons;
- Solo TDD checked by default and Autonomous Program opening advanced settings;
- project name, absolute root, branch, checkout suffix, and run status visible;
- light theme activation;
- 1280px layout with `scrollWidth == innerWidth`;
- 390x844 layout with `scrollWidth == innerWidth`, 358px main, persistent identity,
  and the intended compact header;
- no warning/error console entries before or after the final rebuild/reload.

The viewport override was reset, the test tab closed, and the local server stopped.

## Safety notes

- API routes are an explicit allowlist; there is no arbitrary file or shell endpoint.
- The hub accepts no POST mutation and never shares project tokens or event caches.
- Scheduler commands are generated argument tuples and limited to `squeue`/`qstat`.
- No live scheduler command or cluster job mutation occurred.
- No artifact was published or pushed.
