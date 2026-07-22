# Architecture impact

The AIFLOW v2 modernization intentionally replaces the legacy monolithic workflow with
project-isolated package layers. The dependency direction is now enforced as:

```text
domain / identity / security
  -> state / quality / skills / scheduler
  -> agents / release / integration
  -> controller
  -> API
  -> CLI
```

The controller owns lifecycle and task execution; state owns persistence only. API and
CLI are adapters. Compatibility scripts delegate inward through the CLI and have dated
deprecation entries. P12 moved `RunLifecycle` from `state` to `controller` so the quality
gate can reject state-to-controller back-edges and dependency cycles without an
exception.

This note documents the approved multi-phase modernization diff. It does not waive hard
file, function, complexity, dependency-cycle, layer, deprecation, or per-task diff gates.
