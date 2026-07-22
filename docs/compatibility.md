# AIFLOW v2 compatibility window

The legacy worker, supervisor, modulator, and integration entry points are finite shims
over the modular AIFLOW v2 package. They warn on use and are supported only through
version 0.6.0 or 2027-01-31, whichever arrives first.

New automation must use `aiflow run`, `aiflow controller`, and the package integration
transaction. No new call site may target a deprecated script. Compatibility entries in
`.aiflow/deprecations.toml` name the replacement, owner, parity test, remaining usage
count, removal version, and deadline. Expired entries fail `aiflow quality check`.

Removal requires green compatibility tests, zero remaining call sites, updated install
and documentation surfaces, and archive verification that the old path is absent.
