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
- Cursor remains compatibility-only and is not exercised as an active default.

These limitations do not weaken project isolation, Solo TDD, offline packaging, quality,
recovery, or integration acceptance. They describe deliberately optional external systems
or owner decisions.
