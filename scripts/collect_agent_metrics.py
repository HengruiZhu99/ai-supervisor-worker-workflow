#!/usr/bin/env python3
"""Collect per-agent runtime and token metrics for the AI workflow."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TOKEN_KEYS = {
    "inputTokens": "input_tokens",
    "outputTokens": "output_tokens",
    "cacheReadTokens": "cache_read_tokens",
    "cacheWriteTokens": "cache_write_tokens",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def iso_or_now(value: str | None) -> str:
    parsed = parse_time(value)
    if parsed is None:
        return utc_now()
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def iso_from_timestamp_ms(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def elapsed_ms(started_at: str | None, finished_at: str | None) -> int | None:
    start = parse_time(started_at)
    finish = parse_time(finished_at)
    if start is None or finish is None:
        return None
    return max(0, int((finish - start).total_seconds() * 1000))


def git_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit("collect_agent_metrics.py must run inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    events = []
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return events
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def sum_usage(events: list[dict[str, Any]]) -> dict[str, int]:
    totals = {name: 0 for name in TOKEN_KEYS.values()}
    for event in events:
        usage = event.get("usage")
        if not isinstance(usage, dict):
            continue
        for source, dest in TOKEN_KEYS.items():
            value = usage.get(source, 0)
            if isinstance(value, int):
                totals[dest] += value
    return totals


def cursor_metrics(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    stream_path = root / args.stream if args.stream else None
    events = read_jsonl(stream_path) if stream_path else []
    init = next((event for event in events if event.get("type") == "system" and event.get("subtype") == "init"), {})
    results = [event for event in events if event.get("type") == "result"]
    last_result = results[-1] if results else {}

    event_timestamps = [
        int(event["timestamp_ms"])
        for event in events
        if isinstance(event.get("timestamp_ms"), int)
    ]
    event_wall_ms = None
    if len(event_timestamps) >= 2:
        event_wall_ms = max(event_timestamps) - min(event_timestamps)

    inferred_started_at = iso_from_timestamp_ms(min(event_timestamps)) if event_timestamps else None
    inferred_finished_at = iso_from_timestamp_ms(max(event_timestamps)) if event_timestamps else None
    started_at = iso_or_now(args.started_at or inferred_started_at)
    finished_at = iso_or_now(args.finished_at or inferred_finished_at)
    wall_ms = elapsed_ms(started_at, finished_at)
    if wall_ms is None:
        wall_ms = event_wall_ms

    usage = sum_usage(events)
    return {
        "schema_version": 1,
        "agent": "cursor",
        "role": args.role,
        "reviewer_role": args.reviewer_role or None,
        "job_id": args.job_id or None,
        "attempt": args.attempt,
        "model": init.get("model") or args.model or None,
        "configured_model": args.model or None,
        "session_id": init.get("session_id") or last_result.get("session_id") or None,
        "request_id": last_result.get("request_id") or None,
        "started_at": started_at,
        "finished_at": finished_at,
        "wall_ms": wall_ms,
        "api_ms": last_result.get("duration_api_ms"),
        "duration_ms": last_result.get("duration_ms"),
        "exit_code": args.exit_code,
        "timed_out": bool(args.timed_out),
        "is_error": last_result.get("is_error"),
        "stream_path": args.stream or None,
        "stdout_path": args.stdout or None,
        "stderr_path": args.stderr or None,
        "event_count": len(events),
        **usage,
    }


def parse_codex_tokens(text: str) -> dict[str, int | None]:
    total_tokens = None
    match = re.search(r"tokens used\s*\n\s*([0-9,]+)", text, re.I)
    if match:
        total_tokens = int(match.group(1).replace(",", ""))

    # Leave room for future CLI formats without guessing split fields.
    return {
        "input_tokens": None,
        "output_tokens": None,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "total_tokens": total_tokens,
    }


def plain_log_metrics(args: argparse.Namespace, root: Path, agent: str) -> dict[str, Any]:
    """Metrics for any agent run captured as a plain text log.

    When --stream points at a cursor-agent stream-json capture, exact token
    usage and session metadata are taken from it instead of the lossy
    plain-text token regex.
    """
    log_text = ""
    log_path = root / args.log if args.log else None
    if log_path:
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_text = ""
    started_at = iso_or_now(args.started_at)
    finished_at = iso_or_now(args.finished_at)
    metrics = {
        "schema_version": 1,
        "agent": agent,
        "role": args.role,
        "reviewer_role": None,
        "job_id": args.job_id or None,
        "attempt": args.attempt,
        "run_id": args.run_id or None,
        "model": args.model or None,
        "reasoning_effort": args.reasoning_effort or None,
        "started_at": started_at,
        "finished_at": finished_at,
        "wall_ms": elapsed_ms(started_at, finished_at),
        "exit_code": args.exit_code,
        "log_path": args.log or None,
        **parse_codex_tokens(log_text),
    }
    stream = getattr(args, "stream", "") or ""
    if stream:
        events = read_jsonl(root / stream)
        if events:
            init = next(
                (e for e in events if e.get("type") == "system" and e.get("subtype") == "init"),
                {},
            )
            results = [e for e in events if e.get("type") == "result"]
            last_result = results[-1] if results else {}
            usage = sum_usage(events)
            metrics.update(usage)
            metrics["total_tokens"] = sum(usage.values()) or None
            metrics["model"] = init.get("model") or metrics["model"]
            metrics["session_id"] = init.get("session_id") or last_result.get("session_id")
            metrics["api_ms"] = last_result.get("duration_api_ms")
            metrics["is_error"] = last_result.get("is_error")
            metrics["stream_path"] = stream
            metrics["event_count"] = len(events)
    return metrics


def codex_metrics(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    return plain_log_metrics(args, root, "codex")


def write_metrics(root: Path, metrics: dict[str, Any], output: str | None) -> Path:
    metrics_dir = root / ".ai" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    if output:
        out_path = root / output
    else:
        role = str(metrics.get("role") or "agent")
        job = str(metrics.get("job_id") or metrics.get("run_id") or "run")
        attempt = metrics.get("attempt")
        suffix = f".attempt-{attempt}" if attempt is not None else ""
        out_path = metrics_dir / f"{job}.{role}{suffix}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    runs_path = metrics_dir / "runs.jsonl"
    with runs_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(metrics, sort_keys=True) + "\n")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="kind", required=True)

    cursor = subparsers.add_parser("cursor")
    cursor.add_argument("--role", required=True, choices=["worker", "reviewer"])
    cursor.add_argument("--reviewer-role", default="")
    cursor.add_argument("--job-id", required=True)
    cursor.add_argument("--attempt", type=int, required=True)
    cursor.add_argument("--model", default="")
    cursor.add_argument("--stream", default="")
    cursor.add_argument("--stdout", default="")
    cursor.add_argument("--stderr", default="")
    cursor.add_argument("--started-at", default="")
    cursor.add_argument("--finished-at", default="")
    cursor.add_argument("--exit-code", type=int, required=True)
    cursor.add_argument("--timed-out", action="store_true")
    cursor.add_argument("--output", default="")

    codex = subparsers.add_parser("codex")
    codex.add_argument("--role", default="supervisor")
    codex.add_argument("--run-id", default="")
    codex.add_argument("--job-id", default="")
    codex.add_argument("--attempt", type=int)
    codex.add_argument("--model", default="")
    codex.add_argument("--reasoning-effort", default="")
    codex.add_argument("--log", required=True)
    codex.add_argument("--started-at", default="")
    codex.add_argument("--finished-at", default="")
    codex.add_argument("--exit-code", type=int, required=True)
    codex.add_argument("--output", default="")

    plain = subparsers.add_parser(
        "plain", help="plain-text log metrics for any agent wrapper (cursor-agent supervisor/modulator runs)"
    )
    plain.add_argument("--agent", default="cursor-agent")
    plain.add_argument("--role", default="supervisor")
    plain.add_argument("--run-id", default="")
    plain.add_argument("--job-id", default="")
    plain.add_argument("--attempt", type=int)
    plain.add_argument("--model", default="")
    plain.add_argument("--reasoning-effort", default="")
    plain.add_argument("--log", required=True)
    plain.add_argument(
        "--stream",
        default="",
        help="optional cursor-agent stream-json capture for exact token usage",
    )
    plain.add_argument("--started-at", default="")
    plain.add_argument("--finished-at", default="")
    plain.add_argument("--exit-code", type=int, required=True)
    plain.add_argument("--output", default="")

    args = parser.parse_args()
    root = git_root()
    if args.kind == "cursor":
        metrics = cursor_metrics(args, root)
    elif args.kind == "plain":
        metrics = plain_log_metrics(args, root, args.agent)
    else:
        metrics = codex_metrics(args, root)
    out_path = write_metrics(root, metrics, args.output)
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
