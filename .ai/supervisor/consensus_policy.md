# Consensus Orchestrator Policy

This policy governs the multi-model consensus orchestrator
(`scripts/orchestrator.py`, pure logic in `scripts/consensus_core.py`) used by
the reviewer and supervisor (and optionally the modulator) roles.

## Goal

The same prompt is fed to a panel of models. They compare notes across rounds
and only produce a decision once they **broadly agree**. Disagreement is never
silently resolved into an acceptance.

## Rounds

- **Round 0** is independent: each panelist answers on its own
  (`consensus_vote.agreement: initial`).
- **Rounds 1..K** are compare-notes rounds: each panelist receives the distilled
  positions (verdict, key points, dissent/blocking reasons) of the other
  panelists and revises toward a shared decision or records a reasoned dissent
  (`consensus_vote.agreement: agree|disagree`).
- The loop stops early once the quorum is met; otherwise it runs `--max-rounds`
  rounds (default 3).

## Quorum and convergence

- `unanimous` (default): the panel converges when **all** panelists share the
  same verdict **and** all report `agreement: agree` (round >= 1). At round 0,
  only verdict unanimity can satisfy convergence.
- `majority`: from round 1 on, a strict majority sharing a verdict converges,
  but the minority dissents are recorded and attached to the decision.
- An unparseable or missing `consensus_vote` from any panelist counts as a
  blocking disagreement; it can never be counted as agreement.

## Decision and escalation

The synthesized decision (`consensus.json`) has a `method`:

- `unanimous` / `majority`: the agreed verdict drives the outcome.
  - Reviewer: verdict `accept` -> not blocked; anything else -> blocked with
    merged blocking/dissent reasons.
  - Supervisor: the agreed action is handed to the single executor to apply.
- `no_consensus`: the panel did not reach the quorum within `--max-rounds`.
  - Reviewer: acceptance is **blocked** (`blocked_by` includes
    `consensus:no_consensus`); the job moves to `review_failed` for supervisor
    action, exactly like a blocking reviewer in the legacy path.
  - Supervisor: the executor is told the panel did not converge and instructed
    to be conservative (prefer `WAITING_FOR_WORKER` or opening a human/supervisor
    gate over a risky acceptance or integration).

## Execution safety (supervisor / modulator)

Panelists run **read-only** (`agent_wrapper.py --read-only`, i.e. cursor-agent
`--mode ask`). For the supervisor the panel only *deliberates*; a single
supervisor executor performs all Git/workflow-state mutations after consensus.
This keeps state mutation single-threaded. Panels should use read-only-capable
wrappers; the `codex` wrapper does not yet enforce a read-only sandbox for
panelists, so prefer `cursor-agent` panelists until that is added.

## Configuration

Panels are declared under `agent_wrappers/panels/<id>.json`. Per-role toggles
and overrides:

- Reviewer: `REVIEWER_CONSENSUS_ENABLED` (default 1), `REVIEWER_CONSENSUS_PANEL`,
  `REVIEWER_CONSENSUS_MODELS`, `REVIEWER_CONSENSUS_MAX_ROUNDS`,
  `REVIEWER_CONSENSUS_QUORUM`.
- Supervisor: `SUPERVISOR_CONSENSUS_ENABLED` (default 1),
  `SUPERVISOR_CONSENSUS_PANEL`, `SUPERVISOR_CONSENSUS_MODELS`,
  `SUPERVISOR_CONSENSUS_MAX_ROUNDS`, `SUPERVISOR_CONSENSUS_QUORUM`,
  `SUPERVISOR_CONSENSUS_TIMEOUT`.
- Modulator: `MODULATOR_CONSENSUS_ENABLED` (default 0) and matching
  `MODULATOR_CONSENSUS_*` variables.

## Cost note

Consensus multiplies model calls (panel size x rounds). The reviewer panel runs
its panelists in parallel within a round. Tune `*_MAX_ROUNDS`, panel size, and
`*_QUORUM`, or disable consensus per role, to trade rigor against cost/latency.
