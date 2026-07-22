---
name: cluster-portability
description: Separate portable workflow and scientific code from cluster-specific modules, paths, schedulers, toolchains, and storage assumptions. Use when adding HPC support, reviewing site profiles, migrating clusters, or detecting site contamination in reusable core code.
---

# Cluster Portability

Keep generic core free of cluster names, absolute site paths, module stacks, queues,
accounts, and scheduler mutation commands. Put site behavior in an explicit project/site
profile or reviewed repository-owned script referenced by an argument array.

Audit configuration precedence, environment scrubbing, filesystem semantics, launcher
selection, CPU/GPU/backend selection, resource requests, scratch/checkpoint locations,
and read-only scheduler parsing. Require fixture tests for each scheduler format and a
generic no-cluster configuration. Fail closed when the site is ambiguous.

Preserve scientific workload, units, backend semantics, and reproducibility metadata
across sites. Document remaining site prerequisites without embedding them into core.
