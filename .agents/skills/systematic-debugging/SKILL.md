---
name: systematic-debugging
description: Reproduce and diagnose deterministic or intermittent software failures with bounded hypotheses, normalized signatures, causal evidence, and finite retries. Use for failing tests, crashes, hangs, regressions, build errors, and incorrect scientific results before attempting a fix.
---

# Systematic Debugging

Reproduce the smallest faithful failure before changing production code.

1. Record the exact command, environment, revision, inputs, exit status, and observed
   signature. Treat a missing test, skip, timeout, or changed workload as a result.
2. Reduce the reproduction without changing the failing invariant.
3. Trace data and control flow from the symptom to the earliest incorrect state.
4. State one falsifiable hypothesis and one observation that would disprove it.
5. Run the cheapest discriminating probe. Do not rerun an unchanged failure more than
   twice.
6. Add a regression test that fails for the diagnosed cause, then make the smallest
   coherent correction.
7. Run the focused gate, affected regressions, and `git diff --check`.

Normalize repeated signatures by error type, failing assertion, top relevant frame, and
input class. After three corrections with the same signature, stop editing and perform a
root-cause pass. Stop when no new testable hypothesis exists.

For numerical failures, pre-register units, convention, domain, norm, resolution,
tolerance, and oracle. Never loosen a tolerance or change scientific meaning merely to
make a test pass.
