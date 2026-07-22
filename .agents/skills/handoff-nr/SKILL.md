---
name: handoff-nr
description: Create or verify a durable, evidence-backed handoff for a long-running numerical-relativity, scientific-computing, or HPC Goal-mode implementation. Snapshot exact contract and Git state, preserve re-verification handles, failed approaches, resources, and one next action; resume without unnecessary questions and stop before implementation.
---

# Handoff NR

## Purpose

Move a long scientific implementation to a fresh Codex task without relying on a bloated transcript or a stale prose summary. The handoff is a compact index into authoritative repository state, validation evidence, and re-verification commands.

This skill has two explicit modes:

- **CREATE:** checkpoint the current implementation and write `HANDOFF.md` plus `RESUME_PROMPT.md`.
- **RESUME:** verify a handoff against live repository state and produce a goal restart prompt.

Infer the mode from the user's explicit wording. “Create a handoff”, “checkpoint”, or “move this to a fresh session” means CREATE. “Resume”, “continue from HANDOFF.md”, or “verify this handoff” means RESUME. If no handoff exists, use CREATE. If a handoff exists and the user explicitly asks to continue, use RESUME. Do not ask a mode-selection question.

Read these references before acting:

- `references/HANDOFF_TEMPLATE.md`
- `references/RESUME_GATE.md`

Use `scripts/state_probe.py` to capture or compare repository state when Git and Python are available.

## Operating contract

- Obey all applicable `AGENTS.md` files and repository policies.
- Do not implement production code, redesign the feature, alter acceptance thresholds, or launch an unrelated investigation.
- Do not treat conversation history, `HANDOFF.md`, or `IMPLEMENTATION_STATE.md` as current truth without re-verification.
- Do not duplicate large content already present in `DESIGN.md`, `TDD_PLAN.md`, `GOAL.md`, commits, issues, or evidence files. Reference them by stable path, SHA, ID, and command.
- Redact secrets, credentials, tokens, cookies, private keys, private dataset contents, and unnecessary personal information.
- Prefer a tracked repository state directory selected by `GOAL.md`. Do not make an OS temporary file the only authoritative handoff.
- Never push, merge, force-reset, delete work, or create a checkpoint commit unless `GOAL.md` or the user explicitly authorizes it.
- Finish with one terminal status and stop.

## Shared state model

The normal state directory contains:

- `IMPLEMENTATION_STATE.md`: compact current snapshot, updated atomically;
- `PROGRESS.jsonl`: append-only checkpoint/event history;
- `evidence/`: retained outputs named by acceptance gates;
- `repo-state.json`: machine-captured repository and contract fingerprints;
- `HANDOFF.md`: current continuation packet;
- `RESUME_PROMPT.md`: copy-paste prompt for a fresh task.

If the repository already has another convention, use it and record the path. The state directory should normally be tracked or otherwise guaranteed to move with the workspace. When using Codex's Local/Worktree Handoff, verify that ignored or untracked state files will transfer; otherwise commit them when authorized or preserve them through the repository's supported inclusion mechanism.

## CREATE mode

### 1. Find the implementation contract

Read, in order:

1. applicable `AGENTS.md` files;
2. `DESIGN.md`;
3. `TDD_PLAN.md`;
4. `GOAL.md`;
5. the current `IMPLEMENTATION_STATE.md`;
6. only the tail of `PROGRESS.jsonl` needed to recover the last two checkpoints and active failure history.

If the first three contract files are missing, do not reconstruct them from conversation. Set `HANDOFF_BLOCKED_BY_MISSING_CONTRACT` and name the missing paths.

### 2. Re-establish current truth

Before writing the handoff:

1. Capture contract fingerprints, branch, HEAD, upstream, and worktree status with `state_probe.py capture --ignore <state-directory>` or equivalent safe commands, so the mutable handoff artifacts do not contaminate the production-code status fingerprint.
2. Re-run only the cheap load-bearing checks needed to determine the active milestone's current state.
3. Verify that named evidence artifacts exist and correspond to the recorded commands.
4. Classify every material claim as:
   - `VERIFIED_CURRENT`;
   - `VERIFIED_AT_CHECKPOINT`;
   - `UNVERIFIED`;
   - `STALE`.
5. Attach an exact re-verification command or procedure to every claim that the next action depends on.

Do not start a long build, scaling run, or full regression merely to create a handoff. If such evidence is not current, mark it honestly and preserve its existing artifact and command.

### 3. Check recoverability

Determine whether the workspace can be resumed safely:

- For a clean worktree, record the exact checkpoint commit.
- For a dirty worktree, enumerate every changed/untracked path and explain how it is preserved.
- If work exists only in ignored, temporary, or host-local files that will not survive transfer, create a portable patch or move the artifact into the approved state directory when safe. Do not silently commit or push.
- Record required environment, hardware, datasets, and resource preflight commands.

If material work cannot be recovered, set `HANDOFF_BLOCKED_BY_UNRECOVERABLE_WORKTREE` and stop after preserving as much evidence as safely possible.

### 4. Write a bounded handoff

Write `HANDOFF.md` using the template. It must include:

- why the task exists and the authoritative observable scenario;
- contract paths and fingerprints;
- exact repository state and a verification command;
- one active milestone and one next action;
- gate state with evidence and re-verification handles;
- failed approaches, failure signatures, retry counts, and what would count as new evidence;
- environment/resource requirements and preflight;
- active versus donor/archive sources;
- blockers and a finite resume gate;
- an exact Goal restart prompt.

Write `RESUME_PROMPT.md` containing only the concise fresh-task prompt. Do not copy the entire conversation.

### 5. Update durable state

Atomically update `IMPLEMENTATION_STATE.md` to status `PAUSED_FOR_HANDOFF` and append one `handoff_created` event to `PROGRESS.jsonl`. Do not rewrite or delete earlier events.

Assign exactly one status:

- `HANDOFF_READY`: every load-bearing continuation claim was re-verified and the workspace is recoverable;
- `HANDOFF_READY_WITH_UNVERIFIED_ITEMS`: continuation is safe, but named non-load-bearing evidence must be refreshed later;
- `HANDOFF_BLOCKED_BY_MISSING_CONTRACT`;
- `HANDOFF_BLOCKED_BY_UNRECOVERABLE_WORKTREE`;
- `HANDOFF_BLOCKED_BY_ENVIRONMENT`.

## RESUME mode

### 1. Orient from disk, not memory

Read the contract, state, handoff, and only the necessary tail of the progress log. Do not begin by exploring the whole repository or replaying the transcript.

### 2. Run the resume gate

Follow `references/RESUME_GATE.md` exactly. Run `state_probe.py verify --ignore <state-directory>` when possible, then dereference the active milestone's load-bearing handles.

The handoff is a pointer. Live Git state, files, tests, datasets, CI, and other named authoritative systems determine current truth.

### 3. Reconcile once

A non-contract mismatch may be reconciled once when the correct state is unambiguous and the action is safe, such as:

- the recorded checkpoint is an ancestor of the current branch;
- an evidence file moved but its generating command and content fingerprint still match;
- a baseline status changed and can be re-derived cheaply.

Record the reconciliation in `IMPLEMENTATION_STATE.md` and `PROGRESS.jsonl`. Do not bounce repeatedly between alternatives.

### 4. Ask only for an irreducible material mismatch

Question budget:

- Normal: zero questions.
- Absolute maximum: two questions.
- Maximum question messages: one.

Ask only when two materially different continuation targets remain, a contract changed without an authorized amendment, or an irreversible recovery action is required. Include a recommended safe default. Never ask the user to restate already documented requirements or approve routine continuation.

### 5. Terminate deterministically

Assign exactly one status:

- `RESUME_READY`: material state matches and all next-action handles were re-verified;
- `RESUME_READY_WITH_RECONCILIATION`: one safe, recorded reconciliation was required;
- `RESUME_BLOCKED_BY_STATE_DIVERGENCE`;
- `RESUME_BLOCKED_BY_ENVIRONMENT`;
- `RESUME_BLOCKED_BY_CONTRACT_CHANGE`.

For a ready state, update `IMPLEMENTATION_STATE.md` to `READY_TO_RESUME`, append a `resume_verified` event, write the exact `/goal` command to `RESUME_PROMPT.md`, and stop. Do not ask “should I continue?”.

## Loop guards

1. Perform one repository-state capture per CREATE or RESUME run. Repeat it only after a material reconciliation.
2. Re-run each load-bearing handle at most once during handoff, unless its inputs changed.
3. Do not start expensive validation to make a handoff look fresher.
4. Do not mine the full transcript or full progress log when durable artifacts already identify the objective and active checkpoint.
5. Do not reopen accepted design or test decisions.
6. Do not create a handoff of a handoff. Replace the current `HANDOFF.md`, advance the checkpoint number, and preserve history in `PROGRESS.jsonl`.
7. Do not claim a new task, worktree, commit, push, or successful transfer unless it was actually created and verified.
8. Once artifacts and terminal status are written, stop.

## Final response

Return only a compact result containing:

- mode;
- terminal status;
- `HANDOFF.md`, `RESUME_PROMPT.md`, and state-directory paths;
- exact repository checkpoint (branch and SHA) or the reason it is unavailable;
- unverified items or blocker, if any;
- for ready RESUME mode, the copy-paste `/goal` command.

Do not ask a closing question.
