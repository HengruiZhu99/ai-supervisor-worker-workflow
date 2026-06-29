#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Pure, dependency-free logic for the multi-model consensus orchestrator.

The orchestrator (`scripts/orchestrator.py`) feeds the *same* prompt to a panel
of models, lets them compare notes across rounds, and stops once the panel
broadly agrees. This module owns the parts that must be deterministic and
unit-testable in isolation from any agent process:

* parsing each panelist's machine-checkable ``consensus_vote`` block (and, for
  reviewer panels, the existing ``review_decision`` / ``progress_review``
  blocks),
* deciding whether a round has converged,
* synthesizing the final consensus decision, and
* mapping a reviewer consensus onto the legacy ``reviewer_decisions.json``
  schema so the rest of the worker loop, coverage check, and supervisor review
  are unchanged.

It deliberately has no I/O beyond reading the text it is handed, and uses only
the Python standard library plus the shared tolerant parsers in
``reviewer_report_parsing``.

The ``consensus_vote`` block every panelist must emit::

    ```yaml
    consensus_vote:
      verdict: accept           # role-specific decision token
      agreement: agree          # round 0: "initial"; later: agree|disagree
      confidence: high          # free-form (high/medium/low or 0-1)
      key_points:
        - ...
      dissent_reasons: []       # required non-empty when agreement is disagree
    ```
"""

from __future__ import annotations

from reviewer_report_parsing import (
    parse_bool,
    parse_list_in_section,
    parse_scalar_in_section,
    select_machine_block,
)

# Decision schemas understood by the orchestrator. ``reviewer`` reuses the
# existing reviewer report blocks; ``supervisor`` deliberates over a supervisor
# action; ``generic`` only relies on the consensus_vote block.
REVIEWER_SCHEMA = "reviewer"
SUPERVISOR_SCHEMA = "supervisor"
SPEC_SCHEMA = "spec"
GENERIC_SCHEMA = "generic"
SCHEMAS = (REVIEWER_SCHEMA, SUPERVISOR_SCHEMA, SPEC_SCHEMA, GENERIC_SCHEMA)

# Verdict tokens that never count as agreement; a panel cannot "converge" on
# not having answered.
UNKNOWN_VERDICTS = {"", "unknown"}

REVIEWER_VERDICTS = {"accept", "revise", "needs_supervisor_judgment", "unknown"}

QUORUM_UNANIMOUS = "unanimous"
QUORUM_MAJORITY = "majority"
QUORUMS = (QUORUM_UNANIMOUS, QUORUM_MAJORITY)


def normalize_token(raw: str) -> str:
    """Lowercase and collapse hyphens/spaces to underscores."""
    return raw.strip().strip("'\"").lower().replace("-", "_").replace(" ", "_")


def normalize_verdict(raw: str, schema: str) -> str:
    token = normalize_token(raw)
    if schema == REVIEWER_SCHEMA:
        if token in {"reject", "rejected", "block", "blocked"}:
            return "revise"
        if token in {"needs_supervisor_judgment", "supervisor_judgment", "needs_judgment"}:
            return "needs_supervisor_judgment"
        if token in {"accept", "revise"}:
            return token
        return token or "unknown"
    if schema == SPEC_SCHEMA:
        if token in {"ready", "complete", "approve", "approved", "accept"}:
            return "ready"
        if token in {"needs_revision", "revise", "reject", "incomplete", "not_ready"}:
            return "needs_revision"
        return token or "unknown"
    # supervisor / generic keep the normalized token as-is.
    return token or "unknown"


def normalize_agreement(raw: str) -> str:
    token = normalize_token(raw)
    if token in {"agree", "agrees", "agreed", "yes", "true", "concur"}:
        return "agree"
    if token in {"disagree", "disagrees", "no", "false", "dissent"}:
        return "disagree"
    if token in {"initial", "independent", "first", "na", "n_a", "none"}:
        return "initial"
    return token or "unknown"


def _reviewer_blocks(block: str, verdict: str) -> tuple[bool, list[str]]:
    """Compute whether a reviewer panelist blocks acceptance.

    Mirrors ``analyze_reviewer_reports`` semantics: a panelist blocks when its
    ``review_decision`` block says so, when ``progress_review`` blocks, or when
    its recommendation is anything other than ``accept``.
    """
    reasons: list[str] = []
    blocks_raw = parse_scalar_in_section(block, "review_decision", "blocks_acceptance")
    decision_blocks = parse_bool(blocks_raw) if blocks_raw else verdict not in {"accept"}
    reasons += parse_list_in_section(block, "review_decision", "blocking_reasons")

    progress_blocks_raw = parse_scalar_in_section(block, "progress_review", "blocks_acceptance")
    progress_blocks = parse_bool(progress_blocks_raw) if progress_blocks_raw else False
    if progress_blocks:
        reasons += parse_list_in_section(block, "progress_review", "blocking_reasons") or [
            "progress_review blocks acceptance"
        ]
    blocks = bool(decision_blocks or progress_blocks or verdict not in {"accept"})
    return blocks, reasons


def parse_vote(text: str, schema: str, panelist: str = "", model: str = "", round_index: int = 0) -> dict:
    """Parse a single panelist response into a structured vote.

    Robust to missing blocks: a panelist that fails to emit a usable
    ``consensus_vote`` is treated as a blocking ``disagree`` so a malformed run
    can never be silently counted as agreement.
    """
    errors: list[str] = []
    vote_block = select_machine_block(text, "consensus_vote:")

    if schema == REVIEWER_SCHEMA:
        decision_block = select_machine_block(text, "review_decision:")
        recommendation = parse_scalar_in_section(decision_block, "review_decision", "recommendation")
    else:
        decision_block = vote_block
        recommendation = ""

    raw_verdict = parse_scalar_in_section(vote_block, "consensus_vote", "verdict")
    verdict = normalize_verdict(raw_verdict or recommendation, schema)
    if not vote_block:
        errors.append(f"{panelist or 'panelist'}: missing consensus_vote block")
    if verdict in UNKNOWN_VERDICTS:
        errors.append(f"{panelist or 'panelist'}: unparseable verdict")
    if schema == REVIEWER_SCHEMA and verdict not in REVIEWER_VERDICTS:
        errors.append(f"{panelist or 'panelist'}: unknown reviewer verdict {verdict!r}")

    agreement = normalize_agreement(parse_scalar_in_section(vote_block, "consensus_vote", "agreement"))
    confidence = parse_scalar_in_section(vote_block, "consensus_vote", "confidence")
    key_points = parse_list_in_section(vote_block, "consensus_vote", "key_points")
    dissent_reasons = parse_list_in_section(vote_block, "consensus_vote", "dissent_reasons")

    if schema == REVIEWER_SCHEMA:
        blocks, reasons = _reviewer_blocks(decision_block, verdict)
        blocking_reasons = reasons
    elif schema == SUPERVISOR_SCHEMA:
        blocks = verdict not in {"accept", "accept_job", "no_action", "wait"}
        blocking_reasons = list(dissent_reasons)
    elif schema == SPEC_SCHEMA:
        blocks = verdict not in {"ready"}
        blocking_reasons = list(dissent_reasons)
    else:
        blocks = False
        blocking_reasons = list(dissent_reasons)

    # A disagreement must carry a reason so the panel and supervisor can see why.
    if agreement == "disagree" and not dissent_reasons:
        dissent_reasons = ["disagreement without stated reason"]

    return {
        "panelist": panelist,
        "model": model,
        "round": round_index,
        "verdict": verdict,
        "agreement": agreement,
        "confidence": confidence,
        "key_points": key_points,
        "dissent_reasons": dissent_reasons,
        "blocks_acceptance": bool(blocks),
        "blocking_reasons": blocking_reasons,
        "parse_errors": errors,
    }


def evaluate_round(votes: list[dict], round_index: int) -> dict:
    """Assess agreement for the latest set of votes (one per panelist)."""
    verdicts = [v["verdict"] for v in votes]
    distinct = {v for v in verdicts if v not in UNKNOWN_VERDICTS}
    has_unknown = any(v in UNKNOWN_VERDICTS for v in verdicts)
    verdict_unanimous = len(distinct) == 1 and not has_unknown

    # Round 0 is the independent round: agreement is "initial", so it cannot
    # satisfy the agreement flag. Unanimity of verdict is still meaningful.
    agreements = [v["agreement"] for v in votes]
    all_agree = bool(votes) and all(a == "agree" for a in agreements)

    counts: dict[str, int] = {}
    for verdict in verdicts:
        if verdict in UNKNOWN_VERDICTS:
            continue
        counts[verdict] = counts.get(verdict, 0) + 1
    majority_verdict, majority_count = ("unknown", 0)
    if counts:
        majority_verdict, majority_count = max(counts.items(), key=lambda kv: kv[1])
    total = len(votes)
    majority_ok = total > 0 and majority_count > total / 2

    agreement_ratio = (sum(1 for a in agreements if a == "agree") / total) if total else 0.0

    if round_index == 0:
        # Independent round: only verdict unanimity is achievable here.
        converged = verdict_unanimous
    else:
        converged = verdict_unanimous and all_agree

    return {
        "round": round_index,
        "verdict_unanimous": verdict_unanimous,
        "all_agree": all_agree,
        "converged": converged,
        "majority_verdict": majority_verdict,
        "majority_count": majority_count,
        "majority_ok": majority_ok,
        "agreement_ratio": round(agreement_ratio, 4),
        "verdict_counts": counts,
        "total": total,
    }


def round_converged(votes: list[dict], round_index: int, quorum: str) -> bool:
    """Convergence test used to stop the round loop early."""
    ev = evaluate_round(votes, round_index)
    if ev["converged"]:
        return True
    if quorum == QUORUM_MAJORITY and round_index > 0 and ev["majority_ok"]:
        # Majority quorum still requires the dissenters to have engaged (i.e.
        # this is a compare-notes round), but does not require unanimity.
        return True
    return False


def synthesize(
    *,
    panel: list[dict],
    rounds: list[dict],
    schema: str,
    max_rounds: int,
    quorum: str,
) -> dict:
    """Build the final consensus decision from all completed rounds.

    ``rounds`` is a list of ``{"round": i, "votes": [vote, ...]}`` dicts in
    order. The synthesis uses the final round's votes for the decision but keeps
    the full transcript for auditing.
    """
    errors: list[str] = []
    if not rounds:
        return {
            "schema_version": 1,
            "decision_schema": schema,
            "quorum": quorum,
            "panel": panel,
            "max_rounds": max_rounds,
            "rounds_run": 0,
            "converged": False,
            "method": "no_consensus",
            "verdict": "unknown",
            "agreement_ratio": 0.0,
            "blocks_acceptance": True,
            "blocking_reasons": ["no panel rounds were recorded"],
            "dissents": [],
            "rounds": [],
            "errors": ["no panel rounds were recorded"],
        }

    final = rounds[-1]
    final_votes = final["votes"]
    final_round_index = final["round"]
    ev = evaluate_round(final_votes, final_round_index)

    for vote in final_votes:
        errors.extend(vote.get("parse_errors", []))

    converged = ev["converged"]
    if converged:
        method = "unanimous"
        verdict = final_votes[0]["verdict"]
    elif quorum == QUORUM_MAJORITY and ev["majority_ok"] and final_round_index > 0:
        method = "majority"
        verdict = ev["majority_verdict"]
    else:
        method = "no_consensus"
        verdict = ev["majority_verdict"]

    dissents = [
        {
            "panelist": v["panelist"],
            "model": v["model"],
            "verdict": v["verdict"],
            "agreement": v["agreement"],
            "dissent_reasons": v["dissent_reasons"],
        }
        for v in final_votes
        if v["agreement"] == "disagree" or v["verdict"] != verdict
    ]

    blocking_reasons: list[str] = []
    if method == "no_consensus":
        blocks_acceptance = True
        blocking_reasons.append(
            f"panel did not reach {quorum} agreement after {len(rounds)} round(s)"
        )
        for dissent in dissents:
            for reason in dissent["dissent_reasons"]:
                blocking_reasons.append(f"{dissent['panelist']}: {reason}")
    else:
        # Converged (or majority): the agreed verdict drives blocking.
        if schema == REVIEWER_SCHEMA:
            blocks_acceptance = verdict not in {"accept"}
        elif schema == SUPERVISOR_SCHEMA:
            blocks_acceptance = verdict not in {"accept_job", "no_action", "wait", "accept"}
        elif schema == SPEC_SCHEMA:
            blocks_acceptance = verdict not in {"ready"}
        else:
            blocks_acceptance = False
        if blocks_acceptance:
            seen = set()
            for vote in final_votes:
                for reason in vote.get("blocking_reasons", []) + vote.get("dissent_reasons", []):
                    if reason and reason not in seen:
                        seen.add(reason)
                        blocking_reasons.append(reason)
        if method == "majority":
            for dissent in dissents:
                for reason in dissent["dissent_reasons"]:
                    blocking_reasons.append(f"minority {dissent['panelist']}: {reason}")

    if errors:
        # A malformed panelist response is never silently accepted.
        blocks_acceptance = True

    return {
        "schema_version": 1,
        "decision_schema": schema,
        "quorum": quorum,
        "panel": panel,
        "max_rounds": max_rounds,
        "rounds_run": len(rounds),
        "converged": bool(converged),
        "method": method,
        "verdict": verdict,
        "agreement_ratio": ev["agreement_ratio"],
        "verdict_counts": ev["verdict_counts"],
        "blocks_acceptance": bool(blocks_acceptance),
        "blocking_reasons": blocking_reasons,
        "dissents": dissents,
        "rounds": rounds,
        "errors": errors,
    }


def consensus_to_reviewer_decisions(consensus: dict) -> dict:
    """Map a reviewer consensus onto the legacy ``reviewer_decisions.json`` schema.

    Keeps ``blocked_by``, ``reviewers_complete``, and the per-reviewer fields the
    worker loop and supervisor already read, generalized to N panelists, while
    adding consensus-specific fields.
    """
    final_votes: list[dict] = []
    if consensus.get("rounds"):
        final_votes = consensus["rounds"][-1]["votes"]

    panel_breakdown = [
        {
            "panelist": v["panelist"],
            "model": v["model"],
            "recommendation": v["verdict"],
            "agreement": v["agreement"],
            "blocks_acceptance": v["blocks_acceptance"],
            "blocking_reasons": v["blocking_reasons"],
            "dissent_reasons": v["dissent_reasons"],
        }
        for v in final_votes
    ]

    blocked_by = [v["panelist"] for v in final_votes if v["blocks_acceptance"]]
    if consensus.get("method") == "no_consensus" and "consensus:no_consensus" not in blocked_by:
        blocked_by = ["consensus:no_consensus"] + blocked_by

    errors = list(consensus.get("errors", []))
    reviewers_complete = bool(consensus.get("converged")) and not errors

    result = {
        "schema_version": 2,
        "mode": "consensus",
        "reviewers_complete": reviewers_complete,
        "consensus_converged": bool(consensus.get("converged")),
        "consensus_method": consensus.get("method"),
        "consensus_verdict": consensus.get("verdict"),
        "consensus_rounds_run": consensus.get("rounds_run"),
        "agreement_ratio": consensus.get("agreement_ratio"),
        "blocks_acceptance": bool(consensus.get("blocks_acceptance")),
        "blocked_by": blocked_by,
        "blocking_reasons": consensus.get("blocking_reasons", []),
        "reviewer_recommendation": consensus.get("verdict"),
        "panel": panel_breakdown,
        "dissents": consensus.get("dissents", []),
        "errors": errors,
    }

    # Back-compatible aliases for any consumer still reading reviewer_a/reviewer_b.
    for index in range(2):
        suffix = "a" if index == 0 else "b"
        if index < len(final_votes):
            vote = final_votes[index]
            result[f"reviewer_{suffix}_recommendation"] = vote["verdict"]
            result[f"reviewer_{suffix}_blocks"] = vote["blocks_acceptance"]
            result[f"reviewer_{suffix}_progress_blocks"] = vote["blocks_acceptance"]
        else:
            result[f"reviewer_{suffix}_recommendation"] = consensus.get("verdict")
            result[f"reviewer_{suffix}_blocks"] = bool(consensus.get("blocks_acceptance"))
            result[f"reviewer_{suffix}_progress_blocks"] = bool(consensus.get("blocks_acceptance"))
    return result


def render_consensus_markdown(consensus: dict) -> str:
    """Human-readable summary of a consensus decision."""
    lines: list[str] = []
    lines.append("# Consensus Decision")
    lines.append("")
    lines.append(f"- Decision schema: `{consensus.get('decision_schema')}`")
    lines.append(f"- Quorum policy: `{consensus.get('quorum')}`")
    lines.append(f"- Converged: **{consensus.get('converged')}** (method: `{consensus.get('method')}`)")
    lines.append(f"- Verdict: **{consensus.get('verdict')}**")
    lines.append(f"- Blocks acceptance: **{consensus.get('blocks_acceptance')}**")
    lines.append(
        f"- Rounds run: {consensus.get('rounds_run')} / {consensus.get('max_rounds')}"
        f" (agreement ratio {consensus.get('agreement_ratio')})"
    )
    panel = consensus.get("panel", [])
    if panel:
        lines.append("")
        lines.append("## Panel")
        lines.append("")
        for member in panel:
            lines.append(
                f"- `{member.get('panelist')}` "
                f"(wrapper `{member.get('wrapper')}`, model `{member.get('model')}`)"
            )
    blocking = consensus.get("blocking_reasons", [])
    if blocking:
        lines.append("")
        lines.append("## Blocking reasons")
        lines.append("")
        for reason in blocking:
            lines.append(f"- {reason}")
    dissents = consensus.get("dissents", [])
    if dissents:
        lines.append("")
        lines.append("## Dissents (final round)")
        lines.append("")
        for dissent in dissents:
            reasons = "; ".join(dissent.get("dissent_reasons", [])) or "(no reason given)"
            lines.append(
                f"- `{dissent.get('panelist')}` verdict `{dissent.get('verdict')}`"
                f" / agreement `{dissent.get('agreement')}`: {reasons}"
            )
    errors = consensus.get("errors", [])
    if errors:
        lines.append("")
        lines.append("## Parse errors")
        lines.append("")
        for error in errors:
            lines.append(f"- {error}")
    rounds = consensus.get("rounds", [])
    if rounds:
        lines.append("")
        lines.append("## Round-by-round verdicts")
        lines.append("")
        for entry in rounds:
            votes = entry.get("votes", [])
            summary = ", ".join(
                f"{v['panelist']}={v['verdict']}/{v['agreement']}" for v in votes
            )
            lines.append(f"- Round {entry.get('round')}: {summary}")
    lines.append("")
    return "\n".join(lines)
