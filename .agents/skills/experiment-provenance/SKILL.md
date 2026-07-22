---
name: experiment-provenance
description: Make scientific and performance experiments reproducible by recording immutable code, configuration, environment, input, command, resource, and result identities. Use for numerical validation, benchmarks, parameter studies, or evidence that may support a scientific or engineering claim.
---

# Experiment Provenance

Before running, record the hypothesis, acceptance criterion, code revision and dirty
state, input/config hashes, command argument array, seed, units, numerical convention,
hardware/backend, compiler/runtime versions, and resource limits.

Store raw outputs separately from interpretation. Retain:

- start/end timestamps and exit status;
- discovered test/sample count and exclusions;
- mesh, resolution, timestep, norm, tolerance, and oracle for numerical work;
- warmup, equivalent-work invariant, repetitions, distribution, and noise controls for
  performance work;
- checksums and stable relative evidence paths.

Compare only compatible runs. Label extrapolation, proxy results, unavailable metadata,
and environmental differences explicitly. Never edit a raw result after collection;
write a derived analysis artifact instead.
