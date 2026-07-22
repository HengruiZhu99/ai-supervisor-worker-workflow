---
name: release-readiness
description: Audit a software package or workflow artifact against its release contract, CI matrix, security boundaries, documentation, checksums, and reproducible installation behavior. Use before publishing, tagging, distributing, or declaring an offline artifact ready; do not publish unless explicitly authorized.
---

# Release Readiness

Remain read-only unless the user separately requested fixes. Verify the exact revision
and clean artifact input, then map every release criterion to fresh evidence.

Check supported runtimes, unit/integration/acceptance/UI suites, security and permission
tests, deterministic quality/deprecation gates, skill/custom-agent validation, install /
upgrade / rollback / uninstall, offline operation, license preservation, documentation,
version consistency, archive member safety, and checksums. Inspect the built archive,
not only the source tree, for unexpected paths, secrets, caches, logs, absolute paths,
links, and missing required files.

Report blockers and optional limitations separately. Never push, tag, publish, merge, or
change a license as part of an audit without explicit authorization.
