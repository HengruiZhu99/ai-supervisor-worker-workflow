# P1 permission, backend, and contamination results

Checkpoint date: 2026-07-22

## Acceptance closure

- `AC-PERM-001` closed: Codex commands select `read-only` for read-only roles and
  `workspace-write` for writers, always spell out approval and sandbox policy, reject
  unrestricted extra arguments, and never generate the bypass flag.
- `AC-BACKEND-001` closed: Codex is recommended/default for all current launch surfaces;
  Cursor remains registered with no recommended roles as explicit compatibility opt-in.

Partial evidence retained for `AC-PERM-002`, `AC-BACKEND-002`, `AC-ID-002`, and
`AC-QUALITY-002`; those IDs remain open until parent-preflight wiring, deterministic
quality/no-model evidence, child-environment scrubbing, and canonical-core gates land.

## Model routing

- Sol: writer, supervisor, modulator diagnosis, architect, scientific/engineering review.
- Terra: workflow chat, ordinary/third reviewer, and default unspecified panelist.
- Luna: narrow generic/spec panel role where high-volume consistency/routing is useful.
- Consensus panels remain available but are disabled by default.

## Commands and results

```text
python3 -m unittest discover -s tests/regression -p 'test_permissions_red.py' -v
Ran 3 tests ... OK

python3 -m unittest discover -s tests/regression -p 'test_contamination_red.py' -v
Ran 2 tests ... OK

python3 -m unittest discover -s tests/regression -p 'test_backend_defaults_red.py' -v
Ran 4 tests ... OK

python3 -m unittest discover -s scripts -p 'test_*.py' -v
Ran 85 tests ... OK

python3 -m py_compile <changed Python entrypoints>
bash -n bin/aiflow scripts/worker_loop.sh scripts/supervisor_loop.sh scripts/modulator_loop.sh
```

All commands passed.

## Architecture impact

`worker_loop.sh` lost the embedded project/site/compiler preamble; no replacement generic
behavior was added. `workflow_gui.py` was touched only to change backend/model/timeout and
permission defaults, including replacing its hard-coded read-only Cursor chat invocation
with explicitly sandboxed Codex. The file remains frozen oversized and is scheduled for
coherent API/UI extraction; this checkpoint did not add a responsibility to it.
