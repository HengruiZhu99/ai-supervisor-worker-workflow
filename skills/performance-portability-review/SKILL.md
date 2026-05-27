---
name: performance-portability-review
description: Review Kokkos, MPI, GPU, or performance-portable work for correctness, parity, and maintainability.
---

# Performance Portability Review

## When to Use

Use when reviewing or planning backend, GPU, Kokkos, MPI, or task-parallel implementation work.

## Checklist

- Confirm reference correctness exists before optimization.
- Check memory layout, strides, ownership, and host/device boundaries.
- Inspect reductions, atomics, synchronization, and race conditions.
- Verify serial and parallel/backend parity tests.
- Check deterministic behavior where required.
- Confirm communication assumptions are documented.
- Require performance measurements only when the job asks for performance work.
- Avoid premature optimization before reference behavior is stable.

## Output Format

Return:
1. Correctness risks.
2. Backend parity assessment.
3. Memory and synchronization concerns.
4. Test and benchmark assessment.
5. Required follow-up.

## Common Failure Modes

- Host/device copies are implicit or stale.
- Reductions are nondeterministic without documentation.
- MPI edge cases use one rank only.
- Optimized code diverges from the reference path.
- Benchmarks lack problem size, hardware, or build details.

