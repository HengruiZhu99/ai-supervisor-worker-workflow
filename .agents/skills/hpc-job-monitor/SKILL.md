---
name: hpc-job-monitor
description: Observe HPC scheduler jobs and scientific progress through read-only commands, bounded polling, and resource-aware evidence. Use when asked to monitor Slurm, PBS, LSF, or fixture-based jobs without submitting, cancelling, requeuing, or otherwise mutating scheduler state.
---

# HPC Job Monitor

Use only project-configured read-only scheduler commands. Never submit, cancel, requeue,
hold, release, reprioritize, or modify a job.

1. Verify cluster/site profile and exact job identity.
2. Capture scheduler state, reason, allocation, elapsed/limit, exit status, and resource
   usage with timestamps.
3. Measure domain progress from a scientific step, checkpoint, or declared task event;
   log modification time alone is not progress.
4. Poll with a finite interval, maximum duration, and unchanged-state cap. Make zero
   model calls while nothing changes.
5. Stop at completion, failure, timeout, ambiguity, or the requested observation point.

Return observed facts, commands, timestamps, evidence, and whether triage is warranted.
