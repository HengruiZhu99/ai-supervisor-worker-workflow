# P12 terminal evidence

## Bound state

- base: `e9311a932dc2d5bab57c2cfd7ed734b8e1ca5466`
- implementation freeze: `307169a8cb95f6907a3230bf36bc659706f1ba7d`
- branch: `codex/aiflow-v2-lightweight-multiproject`
- version: `0.4.0.dev0`
- terminal classification: `AIFLOW_V2_READY_WITH_OPTIONAL_LIMITATIONS`
- pre-existing untracked paths preserved: `.DS_Store` and
  `aiflow-v2-lightweight-multiproject-kit/`

## Fresh executable gates

Each supported interpreter passed the same 308-test matrix:

| Python | Unit | Regression | Integration | Acceptance | Compatibility scripts | Total |
|---|---:|---:|---:|---:|---:|---:|
| 3.11.10 | 85 | 106 | 16 | 16 | 85 | 308 |
| 3.12.9 | 85 | 106 | 16 | 16 | 85 | 308 |
| 3.13.7 | 85 | 106 | 16 | 16 | 85 | 308 |
| 3.14.6 | 85 | 106 | 16 | 16 | 85 | 308 |

The required per-interpreter suites were run serially. An exploratory run that loaded
three complete interpreter suites concurrently caused one synthetic 0.1-second heartbeat
TTL miss on 3.11; the exact test then passed 11 consecutive isolated runs and the entire
3.11 matrix passed serially. This was not treated as release evidence.

Additional gates:

- Python compileall: passed on every supported interpreter;
- Ruff format/check: 132 files, passed;
- mypy: 78 source files, passed;
- Bash syntax and ShellCheck error-level scan: passed;
- quality: 198 files, passed against the authorized modernization baseline;
- project verification and 20 canonical skill hashes: passed;
- tracked-file secret scan: zero findings;
- `git diff --check`: passed;
- frontend type/lint/format/unit/build: passed, 6/6 contracts;
- Playwright Chromium, one worker, zero retries: 5/5 passed;
- AthenaK-like C++/CMake Solo flow: passed with CTest and numerical evidence.

The relative `PYTHONPATH=src:.` form is intentionally not used for a quality command
executed from a disposable integration worktree because it would resolve against that
worktree. Audits used an absolute source fallback for the tooling process; candidate
project gates still ran in the isolated worktree. This is an invocation caveat, not a
product failure.

## Offline artifact

Canonical local outputs:

- `dist/aiflow-0.4.0.dev0.pyz`
- `dist/aiflow-0.4.0.dev0.pyz.sha256`
- `dist/aiflow-0.4.0.dev0.pyz.manifest.json`

Artifact SHA-256:
`3494ef74098733121c05d4cbbf01ec0686b6693869cec4b508944479c4fffd59`.

`aiflow package verify` accepted all 198 archive members. A second build in a fresh
temporary directory was byte-identical. All four offline artifact execution, manifest,
tamper, and reproducibility tests passed. The artifact is local and ignored; it was not
published.

## Terminal constraints

No push, default-branch merge, publication, `sudo`, license change, cluster-job mutation,
or discard of pre-existing work occurred. Optional integrations and owner decisions are
listed in `docs/OPTIONAL_LIMITATIONS.md`; none blocks the accepted offline workflow.
