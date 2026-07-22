# AIFLOW

AIFLOW is a lightweight, project-isolated workflow for evidence-first software work with
Codex. It has two modes over one identity, state, quality, recovery, and integration
engine:

- **Solo TDD** (default): one agent, one bounded task, RED → GREEN → refactor → verify →
  cold review.
- **Autonomous Program**: acceptance-ID tasks, finite direct-child agents, isolated
  worktrees, risk-based review, and two-phase integration.

The core runtime uses the Python standard library. The optional GUI is built from
React/TypeScript, but its checked-in assets run without Node. Scheduler monitoring is
fixture-tested and read-only. No cluster mutation command exists.

## Quick start

Install the runtime once from this checkout, then initialize each target explicitly:

```bash
python3 -m pip install -e .
cd /path/to/existing/git-project
aiflow project init --profile solo
```

Before starting a run, set executable argument arrays in `.aiflow/project.toml`.
The RED/focused command must be the same causal test before and after the change, and a
separate regression command is mandatory. For example:

```toml
[commands]
build = ["python3", "-m", "compileall", "-q", "src"]
test_red = ["python3", "-m", "unittest", "tests.test_norm"]
test_focused = ["python3", "-m", "unittest", "tests.test_norm"]
test_regression = ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
```

Then verify and create a bounded task. `--allowed-scope` is repository-relative and
repeatable:

```bash
aiflow project verify
aiflow run start --mode solo \
  --objective "Fix the L2 norm and retain a numerical regression" \
  --acceptance-id AC-NORM-001 \
  --allowed-scope src/norm.py \
  --allowed-scope tests/test_norm.py
```

Or use the offline artifact:

```bash
bin/aiflow package build --distribution-root . --output-dir dist
dist/aiflow-0.4.0.dev0.pyz --project-root /path/to/project project init --profile solo
```

Profiles are cumulative: `solo`, `science`, `hpc`, `orchestrated`, and `full`. Project
files and small skills are hash-locked; the runtime is not copied into the target.

## Solo TDD

```bash
aiflow project init --profile science
aiflow run start --mode solo \
  --objective "Fix the L2 norm and retain a numerical regression" \
  --acceptance-id AC-NORM-001 \
  --allowed-scope src/norm.cpp \
  --allowed-scope tst/unit/test_norm.cpp
aiflow run list
aiflow run resume --run-id RUN_ID --max-idle 1
```

For an AthenaK-style C++/CMake repository, invoke Codex directly with the vendored skill:

```bash
codex exec -C /path/to/AthenaK -m gpt-5.6-sol \
  -s workspace-write -a never \
  '$tdd-solo Fix the bounded norm defect. Preserve units, shapes, tolerances, and CTest evidence.'
```

Solo never launches a subagent. Its evidence contract distinguishes feature, bug,
refactor, numerical, performance, and portability cycles and bounds attempts/questions.

## Autonomous Program

```bash
aiflow project upgrade --profile orchestrated
aiflow run start --mode orchestrated \
  --parent-sandbox workspace-write \
  --objective "Deliver the approved milestone DAG" \
  --acceptance-id AC-M1-001 \
  --task-file .aiflow/tasks/milestone.json
```

An explicit task file is an executable contract, not planning metadata. Each task needs
bounded scope, a discriminating pre-change command, and post-change commands that rerun
that same command; orchestrated projects must also configure `test_regression`:

```json
{
  "tasks": [
    {
      "id": "T0001",
      "objective": "Close the bounded norm defect",
      "kind": "numerical",
      "acceptance_ids": ["AC-M1-001"],
      "allowed_scope": ["src/norm.cpp", "tst/unit/test_norm.cpp"],
      "pre_commands": [["ctest", "--test-dir", "build", "-R", "norm", "--output-on-failure"]],
      "commands": [["ctest", "--test-dir", "build", "-R", "norm", "--output-on-failure"]]
    }
  ]
}
```

The parent is the only controller, state writer, and integrator. Custom agents are
depth-one and role-scoped. Consensus and always-on model watchdogs are off by default.

## Codex model defaults

Defaults were verified against current OpenAI documentation on 2026-07-22:

| Role | Default | Reason |
|---|---|---|
| task router | GPT-5.6 Luna | narrow, high-volume routing |
| codebase mapper, docs researcher, UI auditor, chat | GPT-5.6 Terra | balanced read-heavy work |
| test architect, implementation, scientific/engineering review, release audit | GPT-5.6 Sol | hardest coding and risk decisions |
| style, architecture-size, deprecation gates | no model | deterministic and reproducible |

Cursor remains an explicit compatibility wrapper. GPT-5.3-Codex-Spark is not needed for
the style gate because that gate deliberately makes zero model calls.

## Local GUI

```bash
aiflow gui
```

The server is loopback-only, asks the OS for a free port by default, and prints its URL
plus the path to checkout-scoped endpoint metadata. The mutation token is written only to
that private `0600` runtime file and is removed when the server exits. It enforces Host,
Origin, token, body-size, checkout identity, and state revision. The browser receives a
snapshot plus retained SSE replay. There is no arbitrary file or shell endpoint.

For read-only discovery across explicit projects:

```bash
aiflow hub --project /repo/one --project /repo/two
```

## State and identity

Every request/artifact carries logical project, checkout, worktree, and run identity.
Canonical live state is stored under:

```text
<git-common-dir>/aiflow/runs/<run-id>/
```

Runtime and cache paths are namespaced by checkout ID outside the repository. State uses
one controller lease, revision compare-and-swap, signed atomic snapshots, append-only
checksum events, transaction intent/recovery, and schema migration.

## Quality and integration

```bash
aiflow quality check
aiflow integrate --candidate COMMIT --base-sha BASE --method merge
```

Quality is baseline/no-growth aware and enforces file/function/complexity limits,
deprecation ownership/expiry, thin shims, and no core import of compatibility modules.
Integration applies candidates in a temporary worktree, runs focused/regression/quality
gates, checks target-HEAD CAS, then applies to the target. Pre-apply failure leaves the
target untouched.

## Documentation

- [CLI reference](docs/CLI_REFERENCE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Operations and recovery](docs/OPERATIONS.md)
- [Security model](docs/SECURITY.md)
- [Migration guide](docs/MIGRATION.md)
- [Release and offline artifact](docs/RELEASE.md)
- [Optional limitations](docs/OPTIONAL_LIMITATIONS.md)
- [Accepted modernization evidence](docs/modernization/BUILD_STATE.md)

## Development checks

```bash
python3 -m unittest discover -s tests/unit -p 'test_*.py'
python3 -m unittest discover -s tests/regression -p 'test_*.py'
python3 -m unittest discover -s tests/integration -p 'test_*.py'
python3 -m unittest discover -s tests/acceptance -p 'test_*.py'
npm --prefix frontend ci
npm --prefix frontend run check
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run e2e
bin/aiflow --project-root . quality check
python3 scripts/secret_scan.py
```

CI has no publish or deployment job. This repository does not declare a distributable
license, so publishing a release remains blocked pending an explicit owner choice. This
modernization does not add or change a license.
