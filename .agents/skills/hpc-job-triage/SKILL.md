---
name: hpc-job-triage
description: Diagnose failed, stalled, or resource-limited HPC jobs using scheduler records, application logs, and scientific progress evidence without mutating cluster jobs. Use after a job failure, timeout, out-of-memory event, node issue, or monitor-detected stall.
---

# HPC Job Triage

Remain read-only. Resolve the scheduler, site profile, job/array element, code revision,
input hash, and launch command before diagnosis.

Classify evidence as scheduler/infrastructure, resource exhaustion, launch/environment,
application defect, numerical instability, or indeterminate. Correlate scheduler reason
and exit code with stderr/stdout, resource high-water marks, checkpoints, and the first
domain-invalid state. Distinguish queue delay from runtime stall and log silence from
scientific no-progress.

State one falsifiable cause, supporting and contradicting evidence, confidence, and the
smallest local reproduction or next read-only probe. Recommend changes, but do not apply
scheduler mutations or silently alter the workload.
