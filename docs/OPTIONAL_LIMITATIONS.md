# Optional limitations

The mandatory offline workflow is complete without these optional live integrations:

- live Codex calls are not part of mandatory CI; fake agents make CI deterministic;
- live SLURM/PBS commands and all cluster mutations are excluded from CI and this
  modernization;
- the read-only multi-project hub lists explicitly selected projects but does not merge
  tokens or event streams;
- GUI and hub servers are deliberately loopback-only; remote use requires SSH local
  forwarding;
- the local artifact is not published because the repository has no declared
  distributable license;
- generally reusable skills were validated locally; no marketplace/plugin publication was
  performed;
- Cursor remains compatibility-only and is not exercised as an active default;
- Codex parent permission provenance is validated from the effective invocation and
  environment contract, but is not a cryptographic attestation from the operating system;
- pause/stop take effect at safe controller boundaries and do not hard-cancel an already
  executing backend call;
- one acceptance no-delta replan is deterministic; repeated no-delta work blocks instead
  of opening an unbounded planning loop;
- wall-time budgeting is enforced at controller boundaries, not by asynchronously killing
  every individual external command;
- offline integration can identify only refs present in the local clone; it does not query
  a remote service to infer a different default trunk;
- browser automation covers required responsive, theme, reconnect, isolation, and error
  scenarios, but is not a complete manual contrast, keyboard, or assistive-technology
  audit;
- controller heartbeat ownership is durable enough for local crash recovery but is not a
  distributed consensus or remote-host liveness service;
- the authorized modernization quality exception expires on `2026-08-31` and must be
  removed when the baseline advances.

These limitations do not weaken project isolation, Solo TDD, offline packaging, quality,
recovery, or integration acceptance. They describe deliberately optional external systems
or owner decisions.
