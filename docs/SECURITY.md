# Security and permission model

## Codex

Every wrapper/custom-agent role declares an approval and sandbox policy. Read-only mapping,
research, review, UI, and release agents cannot write. Implementation uses workspace-write.
Recursive child delegation is disabled. The orchestrated parent refuses an unrestricted
permission profile; no bypass flag is emitted.

Model names do not imply permissions. Effective command and filesystem behavior remains
the enforcement boundary.

## Local API

- loopback binding is default; remote bind needs explicit opt-in;
- exact Host and Origin are required;
- each project server has a random session mutation token;
- mutation bodies are JSON and size bounded;
- checkout identity and expected state revision are mandatory for existing-run changes;
- routes are named actions only;
- there is no arbitrary file-read, file-write, or shell endpoint;
- the read-only hub accepts no POST request;
- CSP, no-frame, no-referrer, no-store, and nosniff headers are emitted.

## Repository and process isolation

Inherited `AIFLOW_*` variables cannot redirect project resolution. Runtime/cache paths use
checkout namespaces. Thread/result/handoff records carry checkout, worktree, run, and
expected working directory. Duplicate checkout IDs at different live locations fail
closed.

## State and Git

Only the controller owns canonical state. Revision CAS, same-directory atomic replacement,
checksums, event sequence, intent recovery, and leases prevent silent multi-writer drift.
Integration checks a captured target HEAD immediately before apply and never force-resets
the user's target.

## Release safety

`scripts/secret_scan.py` scans tracked files for credential-shaped values and reports only
path, line, and pattern. The artifact allowlist excludes Git metadata, live state, runtime,
cache, worktrees, backups, and Node dependencies. Both the archive and every internal
payload file are checksummed.

Report security issues privately to the repository owner. No public reporting address is
invented here.
