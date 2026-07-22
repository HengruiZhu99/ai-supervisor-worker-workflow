# Scientific test catalog

Choose tests by failure risk. Do not use every category by default.

## Algebraic and local invariants

Use for tensor symmetries, trace or determinant constraints, normalization, positivity, boundedness, source-term identities, and exact local transformations.

Good oracle: independently derived identity or symbolic/analytic value.

## Analytic and manufactured solutions

Use when a closed-form solution or forced manufactured solution can isolate discretization and implementation errors.

Specify domain, initial and boundary data, forcing, norm, resolution sequence, and expected order.

## Consistency and convergence

Use for discretizations whose claimed order matters. Prefer at least three resolutions or orders, a stated fitting method, and a tolerance around the theoretically expected rate. Distinguish asymptotic convergence from a single error decrease.

## Conservation and constraints

Use for mass, energy, momentum, charge, divergence, Hamiltonian/momentum constraints, generalized-harmonic constraints, Z4 constraints, or other formulation-specific monitors.

Define the norm, normalization, measurement interval, expected trend, and permissible growth.

## Boundary and interface behavior

Use for physical boundaries, excision, punctures, AMR, multipatch, DG/SAT interfaces, ghost zones, prolongation/restriction, flux exchange, and domain decomposition.

Test both nominal propagation and adversarial placement near boundaries or interfaces.

## Limiting and metamorphic behavior

Use when exact outputs are hard to know but transformations imply relations: zero-amplitude limits, symmetry transforms, coordinate changes, resolution changes, domain decomposition changes, unit scaling, or equivalent parameterizations.

## Restart and persistence

Use when checkpoints, restart files, diagnostics, or serialized state change. Compare uninterrupted and restarted trajectories using a defined norm and metadata/version checks.

## Parallel, precision, and device parity

Use when the change touches MPI, threading, vectorization, GPU kernels, mixed precision, reductions, or nondeterministic scheduling.

Define acceptable numerical variation rather than demanding bitwise identity unless bitwise reproducibility is an explicit requirement.

## Long-time and physical validation

Use for drift, stability, waveform phase/amplitude, horizon quantities, equilibrium solutions, turbulence statistics, or other emergent behavior. Set a finite duration and a scientifically justified metric.

## Performance, memory, and scaling

Use only with a stable protocol: fixed hardware/software, warmup, repetitions, aggregation statistic, noise margin, problem size, and comparison baseline. Mark as informative when the environment cannot support a trustworthy gate.

## Negative and failure-path tests

Use for invalid configuration, incompatible restart, unsupported mesh/device combinations, non-finite input, resource exhaustion, and diagnostics. Define the required error type, message content, exit behavior, and absence of partial corruption.

## Anti-patterns

Avoid:

- expected values computed by the same helper being tested;
- golden files regenerated from the candidate implementation without independent review;
- one-resolution “convergence” claims;
- tolerance chosen after observing the candidate result;
- performance gates without a fixed protocol;
- tests that pass when silently skipped;
- reducing runtime, resolution, coverage, or precision to hide a regression.
