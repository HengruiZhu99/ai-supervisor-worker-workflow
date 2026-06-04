# Static Infrastructure Validation Policy

This policy applies before dispatching jobs that prepare generalized harmonic,
XCTS, domain, geometry, operator, tensor, backend, or MPI infrastructure. It
fills the validation gap before time-dependent evolution tests are available.

Each applicable worker task must name its validation class in the task
`progress:` block and state the exact tests, tolerances, backend matrix, artifact
paths, and skip criteria. The worker should implement the scoped feature, not
invent broad validation policy during implementation.

## Validation Classes

- `schema`: deterministic metadata/schema/manifest checks only. Allowed for
  source-role, manifest, or planning slices. Must name the implementation or
  validation job it unlocks.
- `construction`: instantiate runtime objects and verify sizes, shapes,
  extents, ownership, finite values, IDs, labels, and invalid-input behavior.
- `identity`: verify exact or near-exact identities such as inverse maps,
  Jacobian/inverse-Jacobian products, interpolation reproduction of constants,
  derivative of constants, tensor symmetry, or pack/unpack round trips.
- `convergence`: run a resolution ladder against analytic or manufactured data
  and state expected order, norms, tolerances, and pass thresholds.
- `backend_matrix`: compare Serial/OpenMP and available Kokkos backends with
  deterministic tolerances and documented skip criteria for unavailable
  hardware.
- `mpi_device`: validate MPI/domain-decomposition behavior, rank-local
  ownership, exchange payloads, and device-host data movement where applicable.

## Domain Maps

Tasks that introduce or change coordinate maps must include:

- construction tests for valid and invalid parameters;
- finite mapped coordinates over representative logical points;
- identity tests for forward/inverse map round trips when an inverse exists;
- Jacobian determinant sign and nondegeneracy checks over representative points;
- boundary/interface point agreement for shared faces or surfaces;
- clear source-role labels for any formula that remains `TODO_REF_REQUIRED`.

Formula-free metadata jobs may stop at `schema` or `construction`, but must name
the first map or identity test they unlock.

## Jacobians

Tasks that introduce Jacobian or inverse-Jacobian calculations must include:

- shape and tensor-index contract tests;
- finite-value checks over interior and boundary sample points;
- identity checks for `J * J^{-1}` and `J^{-1} * J`;
- comparison to finite differences or analytic manufactured cases when
  practical;
- backend parity if the calculation is device-callable.

## Collocation Coordinates

Tasks that introduce collocation rules must include:

- exact node counts and endpoint behavior for small orders;
- invalid order handling;
- deterministic ordering and layout tests;
- reproduction of documented known nodes for low order;
- backend parity if nodes are produced on device.

## Interpolation And Resampling

Tasks that introduce interpolation or resampling must include:

- constant and low-order polynomial reproduction tests;
- endpoint and boundary behavior;
- invalid shape/order handling;
- convergence on a smooth analytic function when applicable;
- backend parity for Kokkos kernels or device-resident data paths.

## Differentiation Operators

Tasks that introduce derivative, gradient, divergence, curl, Laplacian, filter,
or modal/tail operators must include:

- zero derivative for constants;
- analytic derivative checks for low-order functions;
- convergence ladders for smooth manufactured functions;
- shape/layout tests for all tensor or pack dimensions;
- backend parity for device kernels;
- explicit tolerances tied to order, conditioning, and floating-point precision.

## Tensor Contracts

Tasks that introduce tensor types, index conventions, or layout contracts must
include:

- rank, dimension, component-count, and storage-order tests;
- symmetry/antisymmetry tests where applicable;
- invalid-index behavior where the API supports checks;
- host/device accessibility tests for performance-portable data structures;
- documentation of physical, logical, inertial, and frame conventions.

## Kokkos Backend Behavior

Tasks that introduce or change Kokkos kernels must include:

- Serial backend tests at minimum;
- OpenMP backend tests when configured locally;
- CUDA/HIP/SYCL tests or explicit task-approved skips when unavailable;
- host/device parity for deterministic fixtures;
- device-forbidden API guards for kernel-facing code.

## MPI And Domain Decomposition

Tasks that introduce MPI or domain-decomposition behavior must include:

- deterministic rank ownership and neighbor/interface metadata tests;
- single-rank and multi-rank tests when MPI is available;
- pack/unpack round-trip tests for boundary payloads;
- skip criteria for unavailable MPI launchers or GPU-aware MPI;
- clear distinction between host-staged and direct device-buffer transfers.

## Boundary And Excision Interfaces

Tasks that introduce boundary or excision metadata, interfaces, or conditions
must include:

- boundary/excision label and orientation contract tests;
- shared-interface consistency from both sides;
- invalid or duplicate boundary record handling;
- explicit statement whether labels are metadata-only or carry physical
  boundary-condition semantics;
- a named follow-up job for physical boundary conditions if the current slice is
  metadata-only.
