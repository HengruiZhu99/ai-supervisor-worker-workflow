# Resume gate

A fresh task must not trust a handoff summary as current truth. Use the handoff as an index of authoritative addresses and re-verification handles.

## Required order

1. Read applicable `AGENTS.md` files.
2. Read `DESIGN.md`, `TDD_PLAN.md`, and `GOAL.md`.
3. Read `IMPLEMENTATION_STATE.md` and only the tail needed from `PROGRESS.jsonl`.
4. Run the repository-state probe and compare:
   - contract file fingerprints;
   - repository identity;
   - branch and HEAD;
   - worktree status;
   - active milestone;
   - evidence paths named by the active milestone.
5. Re-run each load-bearing command that the next action depends on.
6. Classify the result:
   - `RESUME_READY`: all material state matches or is safely re-derived;
   - `RESUME_READY_WITH_RECONCILIATION`: a non-contract mismatch was reconciled and recorded;
   - `RESUME_BLOCKED_BY_STATE_DIVERGENCE`: contract, branch, code, or evidence diverged materially;
   - `RESUME_BLOCKED_BY_ENVIRONMENT`: required validation cannot run here.

## Reconciliation rules

- The live repository and named external systems outrank prose claims.
- A contract-file change requires an explicit contract-change record. Do not infer one.
- A changed HEAD is not automatically a blocker. Inspect the commit graph and determine whether the recorded checkpoint is an ancestor, descendant, or unrelated state.
- A dirty worktree is acceptable only when every change is accounted for by path and recoverable from the current workspace, a patch, or an authorized checkpoint commit.
- A missing evidence artifact may be regenerated only by its recorded command; never recreate it from memory.
- Never repeat a failed expensive command solely to see whether it works now. First run its cheap preflight and identify new evidence.

## Question policy

Normally ask zero questions. One message containing at most two questions is allowed only when:

- two materially different repositories or branches could be the intended continuation target;
- a contract fingerprint changed and no authorized amendment explains it;
- an irreversible/high-impact action is required to recover state.

Provide a recommended safe default. Do not ask the user to restate the project or re-approve already accepted decisions.

## Automatic continuation rule

When the resume gate is `RESUME_READY`, do not ask “should I continue?” Produce the exact `/goal` restart prompt and stop. When the user explicitly asked to resume and start, start only if the current Codex surface supports doing so without bypassing approval or safety boundaries.
