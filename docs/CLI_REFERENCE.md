# CLI reference

Global form:

```text
aiflow [--project-root PATH] COMMAND ...
```

Inherited `AIFLOW_*` variables never select a project. The explicit root or current Git
repository is authoritative.

## Checked read-only examples

The integration suite executes every marked command.

<!-- cli-check: aiflow --version -->
<!-- cli-check: aiflow --project-root . project status -->
<!-- cli-check: aiflow --project-root . project verify -->
<!-- cli-check: aiflow --project-root . skills list -->
<!-- cli-check: aiflow --project-root . skills validate -->
<!-- cli-check: aiflow --project-root . quality check -->
<!-- cli-check: aiflow --project-root . gui --check -->
<!-- cli-check: aiflow --project-root . hub --check --project . -->

```bash
aiflow --version
aiflow --project-root . project status
aiflow --project-root . project verify
aiflow --project-root . skills list
aiflow --project-root . skills validate
aiflow --project-root . quality check
aiflow --project-root . gui --check
aiflow --project-root . hub --check --project .
```

## Project lifecycle

```text
project init [--profile core|solo|science|hpc|orchestrated|full]
project status
project verify
project upgrade --profile PROFILE
project rollback TRANSACTION_ID
project uninstall
```

`init` defaults to `solo`. Use `core` for the minimal two-lane DSH workflow: grilling,
Solo TDD, autonomous execution, and handoff, without specialized skills or optional
Codex agent presets. Vendor mode copies selected small skills. Link mode is reserved for
immutable local versions and rejects a mutable source tree.

## Skills

```text
skills list
skills validate
skills doctor
skills sync
```

Repository skills use `.agents/skills`. Doctor also checks user, admin, and plugin scopes
for duplicate names.

## Runs and state

```text
run start --mode solo|orchestrated --objective TEXT [--acceptance-id ID ...]
          [--allowed-scope PATH ...] [--task-kind KIND] [--task-file FILE.json]
run list
run status [--run-id ID]
run resume [--run-id ID] [finite budget options]
run pause [--run-id ID]
run stop [--run-id ID]
run handoff [--run-id ID]
run verify-handoff PATH
state verify|repair|migrate [--run-id ID]
controller run [--run-id ID] [finite budget options]
```

Orchestrated start/resume requires `--parent-sandbox read-only|workspace-write` and
refuses `danger-full-access`.

The default task form requires at least one repeatable, repository-relative
`--allowed-scope`. Before run state is created, `[commands]` in
`.aiflow/project.toml` must provide a discriminating `test_red` command (or
`test_focused` for refactor/performance/portability), must rerun that exact causal
command after the change, and must provide `test_regression`. Commands are argument
arrays, never shell strings.

```toml
[commands]
build = ["python3", "-m", "compileall", "-q", "src"]
test_red = ["python3", "-m", "unittest", "tests.test_widget"]
test_focused = ["python3", "-m", "unittest", "tests.test_widget"]
test_regression = ["python3", "-m", "unittest", "discover", "-s", "tests"]
```

`--task-file` accepts one Solo task or at most 100 orchestrated tasks. Every task must
contain nonempty `allowed_scope`, `pre_commands`, and `commands`; at least one exact
pre-command must appear in its post commands. Dependencies must form a valid DAG, and an
orchestrated project still requires configured `test_regression`. A minimal file is:

```json
{
  "tasks": [
    {
      "id": "T0001",
      "objective": "Fix one bounded defect",
      "kind": "bugfix",
      "acceptance_ids": ["AC-BUG-001"],
      "allowed_scope": ["src/widget.py", "tests/test_widget.py"],
      "pre_commands": [["python3", "-m", "unittest", "tests.test_widget"]],
      "commands": [["python3", "-m", "unittest", "tests.test_widget"]]
    }
  ]
}
```

## Quality and integration

```text
quality baseline
quality check
integrate --candidate COMMIT [--base-sha SHA] [--method merge|cherry-pick]
```

## GUI and hub

```text
gui [--host 127.0.0.1] [--port 0] [--no-open]
hub --project PATH [--project PATH ...] [--host 127.0.0.1] [--port 0]
```

Port `0` asks the operating system for an unused port. Both servers are loopback-only;
the deprecated `--allow-remote` compatibility flag cannot relax that boundary. The GUI
writes its URL and mutation token to a private checkout-scoped `ENDPOINT.json` for its
lifetime. The hub is always read-only.

## Offline package

```text
package build [--distribution-root PATH] [--output-dir DIR]
package verify ARTIFACT.pyz
```

Build emits a zipapp, checksum sidecar, and payload manifest. Verify checks the external
archive checksum, internal file checksums, required assets, and forbidden path classes.
