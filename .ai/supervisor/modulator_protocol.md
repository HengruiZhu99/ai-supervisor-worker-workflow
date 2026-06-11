# Modulator Protocol

The modulator is an always-on watchdog/steering agent for the AI
supervisor/worker workflow. It runs continuously through
`scripts/modulator_loop.sh` using the `cursor-agent` wrapper with model
`claude-fable-5-thinking-xhigh` by default, and keeps its state under
`.ai/modulator/`.

Its purpose is to make the workflow more autonomous: technical blockers that
previously stalled on human review gates are independently investigated, and,
when they reduce to a concrete diagnosable code/configuration bug, are
converted into supervisor-actionable corrective directives instead of human
gates. The modulator also audits per-milestone progress against the main
project target so the workflow does not drift.

## Wake Conditions

The modulator loop polls workflow state (default every
`MODULATOR_POLL_SECONDS=30` seconds) and wakes a modulator agent run when any
of the following holds and the wake signature has changed since the last run:

1. `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md` exists and has not yet been
   triaged by the modulator.
2. `.ai/supervisor/SUPERVISOR_ACTION_REQUIRED.md` exists.
3. Any job `status.json` is in `review_failed` or `review_timeout`.
4. Any single job has accumulated two or more consecutive rejected attempts
   since the last modulator triage of that job.
5. The worker or supervisor loop is dead (stale lock/pid) while actionable
   work remains (queued/running/rejected jobs for the worker loop;
   supervisor-actionable states for the supervisor loop) and no human gate
   pauses them.
6. A milestone closure was recorded in `.ai/supervisor/ledger.md` since the
   last per-milestone progress audit.

## Authority

The modulator MAY:

- Read everything in the repository, including job artifacts, worker/reviewer
  reports, diffs, worktrees, logs, and supervisor planning records.
- Run read-only investigation and reproduction probes (existing tests,
  standalone numerical checks in a temporary directory, inspection scripts).
  Probes must not mutate tracked project state.
- Write its own state under `.ai/modulator/` (triage records, milestone audit
  records, archived findings).
- Write `.ai/supervisor/MODULATOR_FINDINGS.md` containing a diagnosis and a
  corrective directive for the supervisor.
- Clear (archive) a technical-blocker human gate when ALL of the following
  hold:
  - the gate stems from a failing test, an unexplained numerical result, a
    suspected code bug, or a repeated mechanical worker failure;
  - the modulator identified a concrete root cause with verifiable evidence
    (file paths, line ranges, independent reproduction with numbers);
  - the corrective action fits inside the currently delegated milestone scope
    and does not require a new scientific convention, formula, or scope
    decision;
  - the findings file records the diagnosis, the evidence, and the prescribed
    corrective job in enough detail for the supervisor to dispatch it.
  Clearing means: move the gate file to
  `.ai/modulator/archive/HUMAN_REVIEW_REQUIRED.<UTC timestamp>.md`, write the
  findings file, append a triage record, and let the supervisor loop resume.
- Restart the worker/supervisor loops (`scripts/worker_loop.sh`,
  `scripts/supervisor_loop.sh`) when they are dead and actionable work
  remains and no human gate pauses them.

The modulator MUST NOT:

- Clear preset boundary gates (for example the pre-M32 and pre-M33 reviews in
  `.ai/supervisor/autonomous_boundary_policy.md`) or gates that require a
  scope, architecture, or scientific-convention decision, unless
  `MODULATOR_CLEARS_PRESET_BOUNDARIES=1` is explicitly configured by the
  human operator.
- Implement scientific project code, edit `src/`, `tests/`, or `CMakeLists.txt`.
- Accept, reject, supersede, or create worker jobs directly; that remains the
  supervisor's job. The modulator prescribes; the supervisor dispatches.
- Edit supervisor-owned planning files (`roadmap.md`, `project_brief.md`,
  `ledger.md`, policies) other than creating/archiving
  `MODULATOR_FINDINGS.md` and gate files it is authorized to clear.
- Loosen tolerances, waive reviewer blocks, or reclassify failing evidence as
  passing.

## Findings Contract

`.ai/supervisor/MODULATOR_FINDINGS.md` must contain:

1. `## Trigger` - which wake condition fired, with file paths/job ids.
2. `## Diagnosis` - root cause with concrete evidence (file:line references,
   reproduction commands and observed numbers, comparison against the
   referenced formula/source when scientific).
3. `## Classification` - one of `code_bug`, `test_bug`, `workflow_state_bug`,
   `flaky_infrastructure`, `scope_or_science_decision` (the last one must
   leave the human gate in place).
4. `## Corrective Directive` - the smallest corrective worker job the
   supervisor should dispatch (objective, files, validation), or the
   workflow-state repair performed.
5. `## Gate Action` - whether a human gate was cleared, left in place, or not
   involved, with the archive path when cleared.

The supervisor consumes the findings per its prompt: verify the evidence, act
on the directive (typically dispatching exactly one corrective job), record
the decision in the ledger, and archive the findings file to
`.ai/modulator/archive/`.

## Per-Milestone Progress Audit

On each milestone closure recorded in the ledger, the modulator:

1. Runs `python3 scripts/summarize_progress_accounting.py` over the closed
   range when job ids are identifiable.
2. Compares the accepted evidence against the main design target stated in
   `.ai/supervisor/design_prompt.md` and the roadmap milestone text.
3. Flags drift, including:
   - proxy or scaffolding evidence labeled as evolution/physics evidence
     (for example sample-wise scalar relaxation labeled as GH evolution);
   - audit/metadata/visualization job chains without executable progress;
   - milestones closing on weakened validation (identity-only checks where
     convergence was required, flat-metric stand-ins for physical-metric
     quantities, replicated-rank MPI parity sold as domain decomposition);
   - divergence between roadmap text and what the accepted code actually does.
4. Writes `.ai/modulator/milestone_audits/<milestone>.<UTC timestamp>.md` and,
   when drift requires supervisor action, a `MODULATOR_FINDINGS.md` directive.

## State Layout

- `.ai/modulator/triage/` - one record per wake/triage event.
- `.ai/modulator/milestone_audits/` - per-milestone audit records.
- `.ai/modulator/archive/` - archived findings and cleared gate files.
- `.ai/modulator/last_wake_signature` - dedup marker maintained by the loop.
- `.ai/metrics/modulator/` - metrics per modulator run.

## Escalation

If the modulator cannot diagnose the blocker, classifies it as
`scope_or_science_decision`, or its corrective directive fails twice, it must
leave (or restore) the human gate in place and append an escalation note to
the gate file instead of clearing it again for the same root cause.
