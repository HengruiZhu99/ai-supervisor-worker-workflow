---
name: experiment-sweep
description: Design and verify bounded reproducible scientific or performance parameter sweeps with explicit hypotheses, immutable inputs, resource budgets, and deterministic aggregation. Use when a goal requires multiple related experiment configurations rather than one run.
---

# Experiment Sweep

Define the scientific question, independent variables, fixed controls, units, valid
domain, sampling strategy, seed policy, stopping rule, failure policy, and resource
budget before execution. Generate a stable run manifest with one immutable ID and input
hash per point.

Run a small sentinel subset first. Do not launch cluster work unless the user explicitly
authorized it. Resume only missing or invalid points; never overwrite raw evidence.
Aggregate with declared exclusions, uncertainty, and compatible-environment checks.
Retain the manifest, exact commands, raw result handles, checksum index, and analysis
code. Stop when the budget, stopping rule, or ambiguity gate is reached.
