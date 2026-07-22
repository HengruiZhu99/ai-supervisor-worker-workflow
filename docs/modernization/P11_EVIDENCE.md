# P11 evidence: acceptance matrix, CI, and release gates

## Acceptance closed

- `AC-SOLO-002`: retained RED/GREEN/regression/cold-review evidence is validated for
  feature, bug, refactor, numerical/test, performance, and portability work. The
  numerical contract additionally requires units, dimensions, shapes, references,
  tolerances, and convergence evidence. Retries and user questions are bounded.
- `AC-QUALITY-002`: the generic runtime remains project-, user-, site-, and
  toolchain-neutral. The contamination regressions pass and all executable commands
  introduced by this phase are structured argument arrays or named scripts.
- `AC-PACKAGE-001`: the supported Python matrix and backend, frontend, browser,
  acceptance, security, documentation, shell, artifact, archive, and checksum gates
  are encoded in CI and passed locally without publication.

`AC-AUDIT-001` remains open for the independent P12 audits.

## Tests-first record

The evidence validators, deterministic fake agent, scenario matrix, secret scanner,
documented CLI contract, and Playwright flow were introduced as failing focused tests.
The first real-browser run retained its trace, video, and screenshot; it exposed a
test-harness ambiguity around an expected stale-revision `409` and an unscoped Resume
button. The harness was narrowed to the run card and the expected error was explicitly
filtered. The production server was also made safely reusable after the browser run
exposed a finite restart race. Both browser scenarios then passed.

## Fresh local gate

Run on the staged P11 tree on 2026-07-22:

```text
npm --prefix frontend run check                  PASS
npm --prefix frontend run lint                   PASS
npm --prefix frontend test                       PASS (2)
npm --prefix frontend run build                  PASS (196.7 KiB built JS; no drift)
npm --prefix frontend run e2e                    PASS (2 Chromium scenarios)
python3 -m unittest discover -s tests/unit       PASS (76)
python3 -m unittest discover -s tests/regression PASS (24)
python3 -m unittest discover -s tests/integration PASS (13)
python3 -m unittest discover -s tests/acceptance PASS (16)
python3 -m unittest discover -s scripts          PASS (85)
ruff fatal-error selection                       PASS
mypy src/aiflow                                  PASS (51 source files)
bash -n and ShellCheck error selection           PASS
bin/aiflow quality check                         PASS (148 files)
bin/aiflow project verify                        PASS
bin/aiflow skills validate                       PASS (20 skills)
python3 scripts/secret_scan.py                    PASS (zero findings)
bin/aiflow package build/verify                  PASS
git diff --cached --check                        PASS
```

The 15-scenario acceptance matrix covers the six work types plus orchestration with
the deterministic fake agent, multiple milestones, fake metadata, repeat failures,
reviewer ping-pong, restart, stale handoff, target drift, cross-project isolation, and
idle zero-model-call behavior.

## Artifact evidence

- Artifact: `dist/aiflow-0.4.0.dev0.pyz`
- Manifest: `dist/aiflow-0.4.0.dev0.pyz.manifest.json`
- Checksum sidecar: `dist/aiflow-0.4.0.dev0.pyz.sha256`
- Payload files: 110
- Verified archive entries: 171
- SHA-256: `997acfb160b943bc90bf3c84b264244783b2161729a71ae646c3b6a19008219b`

No push, publication, deployment, license change, elevated command, or live scheduler
operation occurred.
