#!/usr/bin/env python3
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

"""Multi-model consensus orchestrator for the AI workflow.

The orchestrator feeds the *same* base prompt to a panel of models, lets them
compare notes across rounds, and stops once the panel broadly agrees. It is
role-neutral: the supervisor loop uses it to deliberate over a decision before a
single executor applies it, and the worker loop uses it to replace the two
independent reviewers with one consensus review panel.

Design:

* Round 0 is independent: every panelist answers the base prompt on its own.
* Rounds 1..K are compare-notes rounds: each panelist sees the distilled
  positions of the others and revises toward a shared decision (or records a
  reasoned dissent).
* The loop stops when the configured quorum is reached (default: unanimous
  verdict with every panelist reporting agreement) or ``--max-rounds`` is hit.
* Every panelist response, prompt, stream capture, and metrics file is written
  under ``--output-dir``; the final decision is ``consensus.json`` /
  ``consensus.md``.

The pure decision logic lives in ``consensus_core``; this module owns process
execution and artifact I/O. ``run_consensus`` takes an injectable ``runner`` so
the round loop is unit-testable without launching real agents.

Exit codes:

* 0   converged and the decision does not block acceptance (clean accept).
* 1   completed but the decision blocks acceptance (revise / no-consensus).
* 2   orchestrator infrastructure error (could not run the panel).
* 124 at least one panelist call timed out.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import consensus_core as cc

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
PANELS_DIR = PACKAGE_ROOT / "agent_wrappers" / "panels"

PEER_EXCERPT_CHARS = 1800
DEFAULT_PANELIST_MODEL = "gpt-5.6-terra"


@dataclass
class Panelist:
    id: str
    wrapper: str = "codex"
    model: str = DEFAULT_PANELIST_MODEL
    reasoning_effort: str = ""
    focus: str = ""


@dataclass
class RunResult:
    text: str
    exit_code: int
    stream_path: str = ""
    stdout_path: str = ""
    metrics_path: str = ""


@dataclass
class OrchestratorConfig:
    role: str
    decision_schema: str
    panel: list[Panelist]
    base_prompt: str
    workspace: str
    output_dir: Path
    max_rounds: int = 3
    quorum: str = cc.QUORUM_UNANIMOUS
    output_format: str = "stream-json"
    read_only: bool = True
    extra_args: str = ""
    timeout: int = 1800
    job_id: str = ""
    attempt: int | None = None
    metrics_role: str = ""
    parallel: bool = True
    artifacts: dict = field(default_factory=dict)


def git_root() -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).resolve()
    except OSError:
        pass
    return PACKAGE_ROOT


def load_panel_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_panel_spec(args: argparse.Namespace) -> dict:
    """Resolve the panel definition from --panel-json, --panel-file, or --panel-id."""
    if args.panel_json:
        return json.loads(args.panel_json)
    if args.panel_file:
        return load_panel_file(Path(args.panel_file))
    if args.panel_id:
        candidate = PANELS_DIR / f"{args.panel_id}.json"
        if candidate.exists():
            return load_panel_file(candidate)
        raise SystemExit(f"unknown panel id {args.panel_id!r}: {candidate} not found")
    # Fall back to a panel named after the role, then the generic default.
    for name in (args.role, "default"):
        candidate = PANELS_DIR / f"{name}.json"
        if candidate.exists():
            return load_panel_file(candidate)
    raise SystemExit("no panel specified and no default panel file found")


def build_panel(spec: dict, args: argparse.Namespace) -> list[Panelist]:
    panelists = [
        Panelist(
            id=str(item.get("id") or f"panelist-{index + 1}"),
            wrapper=str(item.get("wrapper") or "codex"),
            model=str(item.get("model") or ""),
            reasoning_effort=str(item.get("reasoning_effort") or ""),
            focus=str(item.get("focus") or ""),
        )
        for index, item in enumerate(spec.get("panelists", []))
    ]

    model_overrides = [m.strip() for m in args.models.split(",") if m.strip()] if args.models else []
    wrapper_overrides = [w.strip() for w in args.wrappers.split(",") if w.strip()] if args.wrappers else []

    # Grow the panel if more models were supplied than the spec lists.
    while len(panelists) < max(len(model_overrides), len(wrapper_overrides)):
        panelists.append(Panelist(id=f"panelist-{len(panelists) + 1}"))

    for index, panelist in enumerate(panelists):
        if index < len(model_overrides):
            panelist.model = model_overrides[index]
        if index < len(wrapper_overrides):
            panelist.wrapper = wrapper_overrides[index]

    if not panelists:
        raise SystemExit("panel has no panelists")
    if len({p.id for p in panelists}) != len(panelists):
        raise SystemExit("panel panelist ids must be unique")
    return panelists


def consensus_protocol_preamble(
    schema: str, panelist: Panelist, peers: list[dict], round_index: int, max_rounds: int, panel_size: int
) -> str:
    lines: list[str] = []
    lines.append("")
    lines.append("---")
    lines.append("")
    if round_index == 0:
        lines.append(f"## Consensus protocol — Round 1 of up to {max_rounds} (independent)")
        lines.append("")
        lines.append(
            f"You are panelist `{panelist.id}` on a {panel_size}-model consensus panel. "
            "Answer the task above independently this round; the other panelists are "
            "answering the same task without seeing your work."
        )
    else:
        lines.append(
            f"## Consensus protocol — Round {round_index + 1} of up to {max_rounds} (compare notes)"
        )
        lines.append("")
        lines.append(
            f"You are panelist `{panelist.id}`. Below are the other panelists' latest "
            "positions on the SAME task. Weigh their evidence against yours and move "
            "toward a shared decision WHERE THE EVIDENCE SUPPORTS IT. Do not concede a "
            "genuine correctness, safety, numerical, or scope problem just to agree. If "
            "you still disagree after considering their points, keep your verdict and give "
            "concrete dissent reasons."
        )
        lines.append("")
        lines.append(f"### Peer positions (round {round_index})")
        for peer in peers:
            lines.append("")
            lines.append(
                f"#### Peer `{peer['panelist']}` — verdict `{peer['verdict']}`, "
                f"agreement `{peer['agreement']}`"
            )
            key_points = peer.get("key_points") or []
            if key_points:
                lines.append("Key points:")
                for point in key_points:
                    lines.append(f"- {point}")
            dissent = peer.get("dissent_reasons") or []
            if dissent:
                lines.append("Dissent reasons:")
                for reason in dissent:
                    lines.append(f"- {reason}")
            blocking = peer.get("blocking_reasons") or []
            if blocking:
                lines.append("Blocking reasons:")
                for reason in blocking:
                    lines.append(f"- {reason}")

    lines.append("")
    if panelist.focus:
        lines.append(f"Your assigned emphasis on this panel: {panelist.focus}.")
        lines.append("")
    lines.append(
        "At the very end of your response emit exactly one fenced ```yaml block. It must "
        "contain every machine-checkable block this role requires PLUS this consensus_vote "
        "block:"
    )
    lines.append("")
    lines.append("```yaml")
    lines.append("consensus_vote:")
    lines.append("  verdict: <your decision token for this role>")
    if round_index == 0:
        lines.append("  agreement: initial")
    else:
        lines.append("  agreement: agree   # agree only if you broadly agree with the emerging consensus; else disagree")
    lines.append("  confidence: high   # high|medium|low")
    lines.append("  key_points:")
    lines.append("    - <the few load-bearing reasons for your verdict>")
    lines.append("  dissent_reasons: []   # required and non-empty when agreement is disagree")
    lines.append("```")
    lines.append("")
    if schema == cc.REVIEWER_SCHEMA:
        lines.append(
            "Put `consensus_vote` in the SAME yaml block as `diff_coverage`, "
            "`review_decision`, and `progress_review`, and keep `consensus_vote.verdict` "
            "identical to `review_decision.recommendation`."
        )
    return "\n".join(lines)


def build_panelist_prompt(
    base_prompt: str,
    schema: str,
    panelist: Panelist,
    peers: list[dict],
    round_index: int,
    max_rounds: int,
    panel_size: int,
) -> str:
    preamble = consensus_protocol_preamble(schema, panelist, peers, round_index, max_rounds, panel_size)
    return f"{base_prompt}\n{preamble}\n"


def split_extra_args(value: str) -> list[str]:
    return shlex.split(value) if value and value.strip() else []


def make_default_runner(config: OrchestratorConfig):
    root = git_root()

    def run(panelist: Panelist, prompt_text: str, round_index: int) -> RunResult:
        out_dir = config.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        base = f"{panelist.id}.round-{round_index}"
        prompt_path = out_dir / f"{base}.prompt.md"
        stdout_path = out_dir / f"{base}.md"
        stderr_path = out_dir / f"{base}.stderr.log"
        stream_path = out_dir / f"{base}.stream.jsonl"
        metrics_path = out_dir / f"{base}.metrics.json"
        prompt_path.write_text(prompt_text, encoding="utf-8")

        wrapper_cmd = [
            sys.executable,
            str(SCRIPT_DIR / "agent_wrapper.py"),
            "run",
            "--role",
            config.role,
            "--wrapper",
            panelist.wrapper,
            "--model",
            panelist.model,
            "--workspace",
            config.workspace,
            "--prompt-file",
            str(prompt_path),
        ]
        if panelist.reasoning_effort:
            wrapper_cmd.extend(["--reasoning-effort", panelist.reasoning_effort])
        if config.read_only:
            wrapper_cmd.append("--read-only")
        if config.output_format:
            wrapper_cmd.extend(["--output-format", config.output_format])
        if config.extra_args:
            wrapper_cmd.append(f"--extra-args={config.extra_args}")

        exit_code = 0
        raw_stdout = ""
        try:
            completed = subprocess.run(
                wrapper_cmd,
                cwd=config.workspace,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=config.timeout if config.timeout and config.timeout > 0 else None,
                check=False,
            )
            exit_code = completed.returncode
            raw_stdout = completed.stdout or ""
            stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            raw_stdout = (exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")) if exc.stdout else ""
            stderr_path.write_text(f"panelist {panelist.id} timed out after {config.timeout}s\n", encoding="utf-8")

        if config.output_format == "stream-json":
            stream_path.write_text(raw_stdout, encoding="utf-8")
            text = stream_to_text(raw_stdout)
        else:
            text = raw_stdout
            stream_path = Path("")
        stdout_path.write_text(text, encoding="utf-8")

        collect_metrics(
            root=root,
            config=config,
            stream_path=str(stream_path) if str(stream_path) else "",
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            metrics_path=str(metrics_path),
            exit_code=exit_code,
        )

        return RunResult(
            text=text,
            exit_code=exit_code,
            stream_path=str(stream_path) if str(stream_path) else "",
            stdout_path=str(stdout_path),
            metrics_path=str(metrics_path),
        )

    return run


def stream_to_text(raw_stdout: str) -> str:
    converter = SCRIPT_DIR / "cursor_stream_to_text.py"
    if not converter.exists():
        return raw_stdout
    try:
        completed = subprocess.run(
            [sys.executable, str(converter)],
            input=raw_stdout,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return completed.stdout or raw_stdout
    except OSError:
        return raw_stdout


def collect_metrics(
    *,
    root: Path,
    config: OrchestratorConfig,
    stream_path: str,
    stdout_path: str,
    stderr_path: str,
    metrics_path: str,
    exit_code: int,
) -> None:
    collector = SCRIPT_DIR / "collect_agent_metrics.py"
    if not collector.exists():
        return
    cmd = [
        sys.executable,
        str(collector),
        "plain",
        "--agent",
        "orchestrator",
        "--role",
        config.metrics_role or config.role,
        "--run-id",
        Path(metrics_path).stem,
        "--log",
        stdout_path,
        "--exit-code",
        str(exit_code),
        "--output",
        metrics_path,
    ]
    if stream_path:
        cmd.extend(["--stream", stream_path])
    if config.job_id:
        cmd.extend(["--job-id", config.job_id])
    try:
        subprocess.run(cmd, cwd=str(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except OSError:
        pass


def run_consensus(config: OrchestratorConfig, runner=None) -> dict:
    """Drive the consensus rounds and write artifacts. Returns the consensus dict."""
    if runner is None:
        runner = make_default_runner(config)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    panel_meta = [
        {"panelist": p.id, "wrapper": p.wrapper, "model": p.model, "focus": p.focus}
        for p in config.panel
    ]
    panel_size = len(config.panel)
    rounds: list[dict] = []
    timed_out = False

    log_lines: list[str] = [
        f"orchestrator role={config.role} schema={config.decision_schema} "
        f"quorum={config.quorum} max_rounds={config.max_rounds} panel={panel_size}"
    ]

    for round_index in range(config.max_rounds):
        votes: list[dict] = []
        previous_votes = rounds[-1]["votes"] if rounds else []
        previous_by_id = {v["panelist"]: v for v in previous_votes}

        def run_one(panelist: Panelist) -> tuple[Panelist, RunResult]:
            peers = [
                previous_by_id[p.id]
                for p in config.panel
                if p.id != panelist.id and p.id in previous_by_id
            ]
            prompt = build_panelist_prompt(
                config.base_prompt,
                config.decision_schema,
                panelist,
                peers,
                round_index,
                config.max_rounds,
                panel_size,
            )
            return panelist, runner(panelist, prompt, round_index)

        # Within a round, panelists are independent and can run concurrently
        # (subprocess waits release the GIL). Rounds remain strictly sequential
        # because round r+1 depends on round r's positions.
        if config.parallel and panel_size > 1:
            with ThreadPoolExecutor(max_workers=panel_size) as pool:
                results_by_id = {
                    panelist.id: result for panelist, result in pool.map(run_one, config.panel)
                }
            ordered = [(p, results_by_id[p.id]) for p in config.panel]
        else:
            ordered = [run_one(p) for p in config.panel]

        for panelist, result in ordered:
            if result.exit_code == 124:
                timed_out = True
            # run_consensus owns the canonical per-round response artifact so the
            # final-round copy works regardless of what the runner persists.
            (config.output_dir / f"{panelist.id}.round-{round_index}.md").write_text(
                result.text, encoding="utf-8"
            )
            vote = cc.parse_vote(result.text, config.decision_schema, panelist.id, panelist.model, round_index)
            vote["exit_code"] = result.exit_code
            if result.exit_code not in (0, 124):
                vote.setdefault("parse_errors", []).append(
                    f"{panelist.id}: agent exited with code {result.exit_code}"
                )
            votes.append(vote)

        rounds.append({"round": round_index, "votes": votes})
        summary = ", ".join(f"{v['panelist']}={v['verdict']}/{v['agreement']}" for v in votes)
        log_lines.append(f"round {round_index}: {summary}")

        if timed_out:
            # No point spending more (expensive) rounds once a panelist has timed
            # out; the run will be reported as a timeout regardless.
            log_lines.append(f"aborting after round {round_index}: a panelist timed out")
            break
        if cc.round_converged(votes, round_index, config.quorum):
            log_lines.append(f"converged after round {round_index}")
            break

    consensus = cc.synthesize(
        panel=panel_meta,
        rounds=rounds,
        schema=config.decision_schema,
        max_rounds=config.max_rounds,
        quorum=config.quorum,
    )
    consensus["role"] = config.role
    consensus["timed_out"] = timed_out

    # Copy each panelist's final-round response to a stable name.
    if rounds:
        final_index = rounds[-1]["round"]
        for panelist in config.panel:
            src = config.output_dir / f"{panelist.id}.round-{final_index}.md"
            dst = config.output_dir / f"{panelist.id}.final.md"
            if src.exists():
                shutil.copyfile(src, dst)

    (config.output_dir / "consensus.json").write_text(
        json.dumps(consensus, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (config.output_dir / "consensus.md").write_text(
        cc.render_consensus_markdown(consensus), encoding="utf-8"
    )
    (config.output_dir / "orchestrator.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    if config.decision_schema == cc.REVIEWER_SCHEMA and config.artifacts.get("reviewer_decisions_out"):
        mapped = cc.consensus_to_reviewer_decisions(consensus)
        Path(config.artifacts["reviewer_decisions_out"]).write_text(
            json.dumps(mapped, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    return consensus


def consensus_exit_code(consensus: dict) -> int:
    if consensus.get("timed_out"):
        return 124
    if consensus.get("converged") and not consensus.get("blocks_acceptance"):
        return 0
    return 1


def cmd_run(args: argparse.Namespace) -> int:
    spec = resolve_panel_spec(args)
    panel = build_panel(spec, args)

    schema = args.decision_schema or spec.get("decision_schema") or cc.GENERIC_SCHEMA
    if schema not in cc.SCHEMAS:
        raise SystemExit(f"unknown decision schema {schema!r}; choose one of {cc.SCHEMAS}")
    quorum = args.quorum or spec.get("quorum") or cc.QUORUM_UNANIMOUS
    if quorum not in cc.QUORUMS:
        raise SystemExit(f"unknown quorum {quorum!r}; choose one of {cc.QUORUMS}")
    max_rounds = args.max_rounds if args.max_rounds is not None else int(spec.get("max_rounds", 3))
    if max_rounds < 1:
        raise SystemExit("--max-rounds must be >= 1")

    base_prompt = Path(args.base_prompt_file).read_text(encoding="utf-8")

    config = OrchestratorConfig(
        role=args.role,
        decision_schema=schema,
        panel=panel,
        base_prompt=base_prompt,
        workspace=args.workspace,
        output_dir=Path(args.output_dir),
        max_rounds=max_rounds,
        quorum=quorum,
        output_format=args.output_format,
        read_only=not args.no_read_only,
        extra_args=args.extra_args,
        timeout=args.timeout,
        job_id=args.job_id,
        attempt=args.attempt,
        metrics_role=args.metrics_role,
        parallel=not args.sequential,
        artifacts={"reviewer_decisions_out": args.reviewer_decisions_out},
    )

    consensus = run_consensus(config)
    print(json.dumps({
        "converged": consensus.get("converged"),
        "method": consensus.get("method"),
        "verdict": consensus.get("verdict"),
        "blocks_acceptance": consensus.get("blocks_acceptance"),
        "rounds_run": consensus.get("rounds_run"),
        "output_dir": str(config.output_dir),
    }, indent=2))
    return consensus_exit_code(consensus)


def cmd_list_panels(args: argparse.Namespace) -> int:
    panels = []
    if PANELS_DIR.exists():
        for path in sorted(PANELS_DIR.glob("*.json")):
            try:
                spec = load_panel_file(path)
            except (OSError, json.JSONDecodeError) as exc:
                panels.append({"id": path.stem, "error": str(exc)})
                continue
            spec["config_path"] = str(path)
            panels.append(spec)
    print(json.dumps({"panels": panels}, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list-panels", help="list registered panels")
    list_parser.set_defaults(func=cmd_list_panels)

    run_parser = subparsers.add_parser("run", help="run a consensus panel")
    run_parser.add_argument("--role", required=True)
    run_parser.add_argument("--decision-schema", default="")
    run_parser.add_argument("--panel-id", default="")
    run_parser.add_argument("--panel-file", default="")
    run_parser.add_argument("--panel-json", default="")
    run_parser.add_argument("--models", default="", help="comma-separated model overrides, in panelist order")
    run_parser.add_argument("--wrappers", default="", help="comma-separated wrapper overrides, in panelist order")
    run_parser.add_argument("--base-prompt-file", required=True)
    run_parser.add_argument("--workspace", required=True)
    run_parser.add_argument("--output-dir", required=True)
    run_parser.add_argument("--max-rounds", type=int, default=None)
    run_parser.add_argument("--quorum", default="")
    run_parser.add_argument("--output-format", default="stream-json")
    run_parser.add_argument("--no-read-only", action="store_true", help="allow panelists to mutate the workspace (default: read-only)")
    run_parser.add_argument("--extra-args", default="")
    run_parser.add_argument("--timeout", type=int, default=0, help="per-panelist-call timeout in seconds (0 = none)")
    run_parser.add_argument("--sequential", action="store_true", help="run panelists one at a time within a round (default: parallel)")
    run_parser.add_argument("--job-id", default="")
    run_parser.add_argument("--attempt", type=int, default=None)
    run_parser.add_argument("--metrics-role", default="")
    run_parser.add_argument("--reviewer-decisions-out", default="")
    run_parser.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
