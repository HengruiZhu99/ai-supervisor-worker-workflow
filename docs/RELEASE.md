# Offline artifact and release gate

## Build and verify locally

```bash
aiflow package build --distribution-root . --output-dir dist
aiflow package verify dist/aiflow-0.4.0.dev0.pyz
```

Outputs:

```text
dist/aiflow-0.4.0.dev0.pyz
dist/aiflow-0.4.0.dev0.pyz.sha256
dist/aiflow-0.4.0.dev0.pyz.manifest.json
```

The executable zipapp includes the standard-library runtime, built GUI assets, verified
project skills, and custom-agent TOML. It temporarily extracts only profile assets during
project initialization. Tests run it with network package installation disabled.

## Gate

CI covers Python 3.11–3.14, syntax/fatal lint/mypy, unit/regression/integration/acceptance,
legacy compatibility, quality/deprecation, skill/agent hash ownership, ShellCheck,
frontend type/lint/unit/build, generated-asset drift, Playwright with failure traces,
offline artifact/tamper checks, archive checksums, docs examples, and tracked-file secret
scanning.

There is intentionally no publication or deployment job.

## Publication blocker

This repository does not declare a distributable license. A local testing artifact can be
built, but publishing or distributing a release remains blocked until the owner makes an
explicit license decision. The modernization does not add, infer, or modify a license.
