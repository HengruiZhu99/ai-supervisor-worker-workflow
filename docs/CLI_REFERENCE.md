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
project init [--profile solo|science|hpc|orchestrated|full]
project status
project verify
project upgrade --profile PROFILE
project rollback TRANSACTION_ID
project uninstall
```

`init` defaults to `solo`. Vendor mode copies selected small skills. Link mode is reserved
for immutable local versions and rejects a mutable source tree.

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

## Quality and integration

```text
quality baseline
quality check
integrate --candidate COMMIT [--base-sha SHA] [--method merge|cherry-pick]
```

## GUI and hub

```text
gui [--host 127.0.0.1] [--port 8765] [--no-open]
hub --project PATH [--project PATH ...] [--host 127.0.0.1] [--port 8766]
```

Non-loopback binding is rejected unless `--allow-remote` is explicit. The hub is always
read-only.

## Offline package

```text
package build [--distribution-root PATH] [--output-dir DIR]
package verify ARTIFACT.pyz
```

Build emits a zipapp, checksum sidecar, and payload manifest. Verify checks the external
archive checksum, internal file checksums, required assets, and forbidden path classes.
