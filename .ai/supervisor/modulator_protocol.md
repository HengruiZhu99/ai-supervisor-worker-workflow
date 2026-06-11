# Modulator Protocol

The modulator is an always-on watchdog/steering agent for the AI
supervisor/worker workflow. It runs continuously through
`scripts/modulator_loop.sh` using the `cursor-agent` wrapper with model
`claude-fable-5-thinking-xhigh` by default, and keeps its state under
`.ai/modulator/`.

Its purpose is to make the workflow fully autonomous between preset human
boundary gates: every failure that arises between gates is owned by the
modulator. Technical blockers are independently investigated and converted
into supervisor-actionable corrective directives. Scope, architecture, and
scientific-convention decisions that arise mid-tranche are decided by the
modulator itself with recorded rationale. Per-milestone and mid-tranche
progress audits keep the workflow aligned with the main project target. The
human steers through the preset boundary gates and the modulator terminal.

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
7. The worker loop is alive but its log has not advanced for
   `MODULATOR_STALL_MINUTES` (default 30) while a job is in the active
   pipeline (`running`/`reviewing`/`implemented`) - an alive-but-hung
   agent, build, or test.
8. `MODULATOR_AUDIT_EVERY_ACCEPTED` (default 3) new jobs have been accepted
   since the last progress audit - a mid-tranche drift check between
   milestone closures.
9. A new human steering directive exists under `.ai/modulator/steering/`
   (written by the modulator terminal in the workflow GUI).

## Authority

The modulator MAY:

- Read everything in the repository, including job artifacts, worker/reviewer
  reports, diffs, worktrees, logs, and supervisor planning records.
- Run read-only investigation and reproduction probes (existing tests,
  standalone numerical checks in a temporary directory, inspection scripts).
  Probes must not mutate tracked project state.
- Write its own state under `.ai/modulator/` (triage records, milestone audit
  records, decision records, archived findings, processed steering
  directives).
- Write `.ai/supervisor/MODULATOR_FINDINGS.md` containing a diagnosis and a
  corrective directive for the supervisor.
- Clear (archive) a technical-blocker human gate when ALL of the following
  hold:
  - the gate stems from a failing test, an unexplained numerical result, a
    suspected code bug, or a repeated mechanical worker failure;
  - the modulator identified a concrete root cause with verifiable evidence
    (file paths, line ranges, independent reproduction with numbers);
  - the corrective action fits inside the currently delegated milestone scope;
  - the findings file records the diagnosis, the evidence, and the prescribed
    corrective job in enough detail for the supervisor to dispatch it.
  Clearing means: move the gate file to
  `.ai/modulator/archive/HUMAN_REVIEW_REQUIRED.<UTC timestamp>.md`, write the
  findings file, append a triage record, and let the supervisor loop resume.
- Decide non-preset scope, architecture, and scientific-convention questions
  that arise between preset boundary gates, and clear the associated gates.
  The decision must be grounded in `.ai/supervisor/design_prompt.md`, the
  roadmap target, the cited public references, and the accepted evidence; it must
  preserve scientific meaning and choose the smallest scope consistent with
  the roadmap. Every such decision requires a decision record under
  `.ai/modulator/decisions/decision.<UTC timestamp>.md` with rationale,
  references, alternatives considered, and the resulting directive, plus a
  `MODULATOR_FINDINGS.md` entry carrying the decision to the supervisor.
- Restart the worker/supervisor loops (`scripts/worker_loop.sh`,
  `scripts/supervisor_loop.sh`) when they are dead and actionable work
  remains and no human gate pauses them.
- Kill a hung agent/build/test process group (never the loop processes
  themselves) when stall detection fired and inspection confirms a genuine
  hang rather than a long-running legitimate command, letting the loop's
  stale-state recovery requeue the attempt.
- Honor human steering directives from `.ai/modulator/steering/` as binding
  operator instructions, then archive them to
  `.ai/modulator/steering/processed/`.

The modulator MUST NOT:

- Clear preset boundary gates (listed in
  `.ai/supervisor/autonomous_boundary_policy.md`), unless
  `MODULATOR_CLEARS_PRESET_BOUNDARIES=1` is explicitly configured by the
  human operator.
- Make a decision that contradicts an explicit prior human instruction or
  expands the project beyond the human-approved roadmap; such
  questions go back to a human gate or the modulator terminal.
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
   `flaky_infrastructure`, `scope_or_science_decision`. A
   `scope_or_science_decision` requires a decision record under
   `.ai/modulator/decisions/` and must state the decision taken; it goes to
   a human only when it contradicts an explicit prior human instruction or
   exceeds the approved roadmap.
4. `## Corrective Directive` - the smallest corrective worker job the
   supervisor should dispatch (objective, files, validation), or the
   workflow-state repair performed, or the decision the supervisor must now
   plan around.
5. `## Gate Action` - whether a human gate was cleared, left in place, or not
   involved, with the archive path when cleared.

The supervisor consumes the findings per its prompt: verify the evidence, act
on the directive (typically dispatching exactly one corrective job), record
the decision in the ledger, and archive the findings file to
`.ai/modulator/archive/`.

## Progress Audits

On each milestone closure recorded in the ledger (wake condition 6) and every
`MODULATOR_AUDIT_EVERY_ACCEPTED` accepted jobs (wake condition 8), the
modulator:

1. Runs `python3 scripts/summarize_progress_accounting.py` over the relevant
   range when job ids are identifiable.
2. Compares the accepted evidence against the main design target stated in
   `.ai/supervisor/design_prompt.md` and the roadmap milestone text.
3. Flags drift, including:
   - proxy or scaffolding evidence labeled as evolution/physics evidence
     (for example proxy relaxation dynamics labeled as full-system evolution);
   - audit/metadata/visualization job chains without executable progress;
   - milestones closing on weakened validation (identity-only checks where
     convergence was required, flat-metric stand-ins for physical-metric
     quantities, replicated-rank MPI parity sold as domain decomposition);
   - divergence between roadmap text and what the accepted code actually does.
4. Writes `.ai/modulator/milestone_audits/<milestone-or-audit>.<UTC
   timestamp>.md` and, when drift requires supervisor action, a
   `MODULATOR_FINDINGS.md` directive.

## Modulator Terminal

The workflow GUI embeds a modulator terminal (it replaces the old workflow
chat box). Messages typed there are answered by a one-shot modulator-role
agent with full repository context and conversation history under
`.ai/modulator/terminal_history.jsonl`. When a message contains an operator
directive that should change workflow behavior (pause/redirect dispatch,
reprioritize, impose a constraint, overrule a modulator decision), the
terminal agent records it as a steering file
`.ai/modulator/steering/steering.<UTC timestamp>.md`; the always-on loop
wakes on it (wake condition 9) and honors it as a binding instruction. The
terminal is the human's between-gates steering channel; preset boundary gates
remain the structured review channel.

## State Layout

- `.ai/modulator/triage/` - one record per wake/triage event.
- `.ai/modulator/milestone_audits/` - per-milestone and mid-tranche audit
  records.
- `.ai/modulator/decisions/` - recorded scope/architecture/convention
  decisions with rationale.
- `.ai/modulator/steering/` - pending human steering directives;
  `processed/` under it holds honored ones.
- `.ai/modulator/terminal_history.jsonl` - modulator terminal conversation.
- `.ai/modulator/archive/` - archived findings and cleared gate files.
- `.ai/modulator/last_wake_signature` - dedup marker maintained by the loop.
- `.ai/metrics/modulator/` - metrics per modulator run.

## Escalation

If the modulator cannot diagnose a blocker after genuine investigation, if a
corrective directive fails twice for the same root cause, or if a decision
would contradict an explicit prior human instruction or exceed the approved
roadmap, it must leave (or restore) the human gate in place, append an
escalation note to the gate file, and summarize the open question so the
human can answer it at the gate or through the modulator terminal.
