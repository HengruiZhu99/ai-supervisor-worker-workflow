#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

# Always-on modulator: watchdog/steering agent for the AI workflow.
# Protocol: .ai/supervisor/modulator_protocol.md
MODULATOR_POLL_SECONDS="${MODULATOR_POLL_SECONDS:-30}"
MODULATOR_RUNS_DIR="${MODULATOR_RUNS_DIR:-.ai/modulator_runs}"
LOOP_LOCK_DIR="${MODULATOR_LOOP_LOCK_DIR:-.ai/supervisor_runs}"
MODULATOR_AGENT_WRAPPER="${MODULATOR_AGENT_WRAPPER:-cursor-agent}"
if [[ -z "${MODULATOR_MODEL:-}" ]]; then
  if [[ "$MODULATOR_AGENT_WRAPPER" == "codex" ]]; then
    MODULATOR_MODEL="gpt-5.5"
  else
    MODULATOR_MODEL="gpt-5.5-high"
  fi
fi
if [[ -z "${MODULATOR_EXTRA_ARGS+x}" ]]; then
  if [[ "$MODULATOR_AGENT_WRAPPER" == "cursor-agent" ]]; then
    MODULATOR_EXTRA_ARGS="--force"
  else
    MODULATOR_EXTRA_ARGS=""
  fi
fi
MODULATOR_CLEARS_PRESET_BOUNDARIES="${MODULATOR_CLEARS_PRESET_BOUNDARIES:-0}"
MODULATOR_RESTART_LOOPS="${MODULATOR_RESTART_LOOPS:-1}"
# Minutes without worker-loop log progress before an alive-but-hung run wakes
# the modulator; 0 disables stall detection.
MODULATOR_STALL_MINUTES="${MODULATOR_STALL_MINUTES:-30}"
# Run a mid-tranche progress audit every N newly accepted jobs; 0 disables.
MODULATOR_AUDIT_EVERY_ACCEPTED="${MODULATOR_AUDIT_EVERY_ACCEPTED:-3}"
export MODULATOR_STALL_MINUTES MODULATOR_AUDIT_EVERY_ACCEPTED
MODULATOR_STATE_DIR=".ai/modulator"
HUMAN_GATE=".ai/supervisor/HUMAN_REVIEW_REQUIRED.md"
SUPERVISOR_ACTION_REQUEST=".ai/supervisor/SUPERVISOR_ACTION_REQUIRED.md"
MODULATOR_FINDINGS=".ai/supervisor/MODULATOR_FINDINGS.md"
LOOP_LOCK=""

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

for cmd in git python3; do
  require_command "$cmd"
done

mkdir -p "$MODULATOR_RUNS_DIR" "$LOOP_LOCK_DIR" \
  "$MODULATOR_STATE_DIR/triage" "$MODULATOR_STATE_DIR/milestone_audits" \
  "$MODULATOR_STATE_DIR/archive"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOW_PACKAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export AI_WORKFLOW_PACKAGE_ROOT="${AI_WORKFLOW_PACKAGE_ROOT:-$WORKFLOW_PACKAGE_ROOT}"
workflow_commit="$(git -C "$SCRIPT_DIR/.." rev-parse --short HEAD 2>/dev/null || git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "workflow_commit=$workflow_commit"
echo "modulator_agent_wrapper=$MODULATOR_AGENT_WRAPPER"
echo "modulator_model=$MODULATOR_MODEL"
echo "modulator_clears_preset_boundaries=$MODULATOR_CLEARS_PRESET_BOUNDARIES"

lock_pid_alive() {
  local lock_dir="$1"
  local pid
  [[ -s "$lock_dir/pid" ]] || return 1
  pid="$(cat "$lock_dir/pid" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

cleanup_loop_lock() {
  if [[ -n "${LOOP_LOCK:-}" ]]; then
    rm -f "$LOOP_LOCK/pid" "$LOOP_LOCK/started_at" "$LOOP_LOCK/workflow_commit" 2>/dev/null || true
    rmdir "$LOOP_LOCK" 2>/dev/null || true
    LOOP_LOCK=""
  fi
}

acquire_loop_lock() {
  local lock_dir="$LOOP_LOCK_DIR/modulator_loop.lock"
  if mkdir "$lock_dir" 2>/dev/null; then
    LOOP_LOCK="$lock_dir"
  else
    if lock_pid_alive "$lock_dir"; then
      echo "modulator_loop already running with pid $(cat "$lock_dir/pid" 2>/dev/null || echo unknown)"
      exit 0
    fi
    rm -f "$lock_dir/pid" "$lock_dir/started_at" "$lock_dir/workflow_commit" 2>/dev/null || true
    rmdir "$lock_dir" 2>/dev/null || true
    if ! mkdir "$lock_dir" 2>/dev/null; then
      echo "failed to acquire modulator loop lock: $lock_dir" >&2
      exit 1
    fi
    LOOP_LOCK="$lock_dir"
  fi
  printf '%s\n' "$$" >"$LOOP_LOCK/pid"
  date -u +"%Y-%m-%dT%H:%M:%SZ" >"$LOOP_LOCK/started_at"
  printf '%s\n' "$workflow_commit" >"$LOOP_LOCK/workflow_commit"
}

record_event() {
  python3 scripts/record_workflow_event.py "$@" >/dev/null 2>&1 || true
}

trap cleanup_loop_lock EXIT
trap 'cleanup_loop_lock; exit 130' INT
trap 'cleanup_loop_lock; exit 143' TERM

acquire_loop_lock

utc_now() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

commit_workflow_records() {
  python3 scripts/commit_workflow_records.py --message "workflow: record modulator state" || true
}

# Emits "reason1,reason2|signature" on stdout. Empty reasons mean no wake.
wake_state() {
  python3 - <<'PY'
import hashlib
import json
from pathlib import Path

reasons = []
signature_parts = []

gate = Path(".ai/supervisor/HUMAN_REVIEW_REQUIRED.md")
if gate.exists():
    reasons.append("human_gate_open")
    # Hash only the gate content above the modulator's own appended notes so
    # an informational `## Modulator Triage` note does not change the wake
    # signature and self-trigger another wake (observed 2026-06-11).
    try:
        gate_text = gate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        gate_text = ""
    gate_core = gate_text.split("\n## Modulator Triage", 1)[0]
    gate_digest = hashlib.sha256(gate_core.encode("utf-8")).hexdigest()[:16]
    signature_parts.append(f"gate:{gate_digest}")

action = Path(".ai/supervisor/SUPERVISOR_ACTION_REQUIRED.md")
if action.exists():
    reasons.append("supervisor_action_required")
    signature_parts.append(f"action:{action.stat().st_mtime_ns}")

job_states = {}
for status_path in sorted(Path(".ai/jobs").glob("J*/status.json")):
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        job_states[status_path.parent.name] = ("invalid", 0)
        continue
    job_states[status_path.parent.name] = (
        str(data.get("state", "unknown")),
        int(data.get("attempt") or 0),
    )

for job_id, (state, attempt) in sorted(job_states.items()):
    if state == "blocked":
        reasons.append(f"worker_blocked:{job_id}")
        signature_parts.append(f"{job_id}:{state}:{attempt}")
    if state in {"review_failed", "review_timeout"}:
        reasons.append(f"review_failure:{job_id}")
        signature_parts.append(f"{job_id}:{state}:{attempt}")
    if state == "rejected" and attempt >= 2:
        reasons.append(f"repeated_rejection:{job_id}")
        signature_parts.append(f"{job_id}:{state}:{attempt}")

def lock_alive(name: str) -> bool:
    pid_path = Path(f".ai/supervisor_runs/{name}.lock/pid")
    try:
        pid = int(pid_path.read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        Path(f"/proc/{pid}").stat()
        return True
    except OSError:
        return False

worker_pipeline = {"queued", "running", "rejected", "implemented", "reviewing"}
supervisor_actionable = {"ready_for_review", "blocked", "review_failed", "review_timeout", "invalid"}
states = {state for state, _ in job_states.values()}
findings = Path(".ai/supervisor/MODULATOR_FINDINGS.md")

if not gate.exists():
    if states & worker_pipeline and not lock_alive("worker_loop"):
        reasons.append("worker_loop_dead_with_work")
        signature_parts.append("worker_loop:dead")
    if (states & supervisor_actionable or findings.exists()) and not lock_alive("supervisor_loop"):
        reasons.append("supervisor_loop_dead_with_work")
        signature_parts.append("supervisor_loop:dead")

# Milestone-closure detection: new ledger section headers that look like
# milestone/boundary closure events since the last recorded header set.
ledger = Path(".ai/supervisor/ledger.md")
headers: list[str] = []
if ledger.exists():
    try:
        headers = [
            line.strip()
            for line in ledger.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.startswith("## ")
        ]
    except OSError:
        headers = []
state_dir = Path(".ai/modulator")
state_dir.mkdir(parents=True, exist_ok=True)
known_path = state_dir / "ledger_headers.txt"
known = set()
if known_path.exists():
    known = set(known_path.read_text(encoding="utf-8", errors="replace").splitlines())
new_headers = [header for header in headers if header not in known]
import re
closure_re = re.compile(r"(?i)milestone|boundary|m\d+(\.\d+)?\b.*(closed|complete|closure|accepted)")
closure_headers = [header for header in new_headers if closure_re.search(header)]
if closure_headers:
    reasons.append("milestone_activity")
    digest = hashlib.sha256("\n".join(closure_headers).encode("utf-8")).hexdigest()[:16]
    signature_parts.append(f"ledger:{digest}")
if new_headers:
    known_path.write_text("\n".join(headers) + "\n", encoding="utf-8")

# Stall detection: an alive worker loop whose log stops advancing while a job
# is in the active pipeline means a hung agent/build/test, which the dead-loop
# check above cannot see.
import os
import time

stall_minutes = int(os.environ.get("MODULATOR_STALL_MINUTES", "30") or "0")
stall_states = {"running", "reviewing", "implemented"}
stalled_jobs = sorted(
    job_id for job_id, (state, _) in job_states.items() if state in stall_states
)
if stall_minutes > 0 and stalled_jobs and lock_alive("worker_loop"):
    log = Path(".ai/supervisor_runs/worker_loop.log")
    try:
        log_mtime = log.stat().st_mtime
    except OSError:
        log_mtime = time.time()
    if time.time() - log_mtime > stall_minutes * 60:
        jobs_tag = ",".join(stalled_jobs)
        reasons.append(f"worker_stalled:{jobs_tag}")
        signature_parts.append(f"stall:{jobs_tag}:{int(log_mtime)}")

# Mid-tranche audit: wake every N newly accepted jobs so drift is caught
# between milestone closures, not only at them.
audit_every = int(os.environ.get("MODULATOR_AUDIT_EVERY_ACCEPTED", "3") or "0")
accepted_count = sum(1 for state, _ in job_states.values() if state == "accepted")
audit_count_path = state_dir / "last_audit_accepted_count"
last_audited = None
try:
    last_audited = int(audit_count_path.read_text().strip())
except (OSError, ValueError):
    # First run: baseline without a retroactive audit over old jobs.
    audit_count_path.write_text(f"{accepted_count}\n", encoding="utf-8")
if (
    audit_every > 0
    and last_audited is not None
    and accepted_count >= last_audited + audit_every
):
    reasons.append("mid_tranche_audit")
    signature_parts.append(f"audit:{accepted_count}")
    audit_count_path.write_text(f"{accepted_count}\n", encoding="utf-8")

# Human steering: directives recorded by the modulator terminal. Each file is
# processed once; the modulator archives it after honoring it.
steering_dir = state_dir / "steering"
steering_seen_path = state_dir / "steering_seen.txt"
seen = set()
if steering_seen_path.exists():
    seen = set(
        steering_seen_path.read_text(encoding="utf-8", errors="replace").splitlines()
    )
pending = (
    sorted(p.name for p in steering_dir.glob("steering.*.md"))
    if steering_dir.exists()
    else []
)
new_steering = [name for name in pending if name not in seen]
if new_steering:
    reasons.append("human_steering")
    digest = hashlib.sha256("\n".join(new_steering).encode("utf-8")).hexdigest()[:16]
    signature_parts.append(f"steering:{digest}")
    steering_seen_path.write_text(
        "\n".join(sorted(seen | set(pending))) + "\n", encoding="utf-8"
    )

# Root-cause priority lock enforcement. This catches a later supervisor
# dispatch that bypasses the lock even when no new steering file exists.
root_lock = Path(".ai/supervisor/ROOT_CAUSE_PRIORITY_LOCK.md")
if root_lock.exists():
    try:
        lock_text = root_lock.read_text(encoding="utf-8", errors="replace")
    except OSError:
        lock_text = ""
    active_after_match = re.search(r"^\s*active_after_job:\s*(J\d{4,})\s*$", lock_text, re.MULTILINE)

    def job_number(name: str) -> int | None:
        match = re.match(r"^J(\d{4,})$", name)
        return int(match.group(1)) if match else None

    active_after_num = (
        job_number(active_after_match.group(1)) if active_after_match is not None else None
    )

    def has_upstream_trace(task_text: str) -> bool:
        if not re.search(r"^##\s+Upstream Trace\s*$", task_text, re.IGNORECASE | re.MULTILINE):
            return False
        required = [
            "Failing milestone/gate",
            "Measured symptom",
            "Suspected upstream cause",
            "Public reference or derivation source",
            "Algorithmic decision or implementation change expected",
            "Validation close/falsify criterion",
            "Why this is not peripheral cleanup",
        ]
        for label in required:
            if not re.search(r"^\s*[-*]\s*" + re.escape(label) + r"\s*:", task_text, re.IGNORECASE | re.MULTILINE):
                return False
        return True

    post_lock_states = {
        "queued",
        "running",
        "rejected",
        "implemented",
        "reviewing",
        "ready_for_review",
        "blocked",
        "review_failed",
        "review_timeout",
        "accepted",
    }
    violations = []
    for status_path in sorted(Path(".ai/jobs").glob("J*/status.json")):
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        job_id = str(data.get("id") or status_path.parent.name)
        number = job_number(job_id)
        if active_after_num is not None and number is not None and number <= active_after_num:
            continue
        state = str(data.get("state", ""))
        if state not in post_lock_states:
            continue
        task_path = status_path.parent / "task.md"
        try:
            task_text = task_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            task_text = ""
        if not has_upstream_trace(task_text):
            violations.append(f"{job_id}:{state}:missing_or_incomplete_upstream_trace")
    if violations:
        reasons.append("root_lock_violation")
        digest = hashlib.sha256("\n".join(violations).encode("utf-8")).hexdigest()[:16]
        signature_parts.append(f"root_lock:{digest}")

signature = hashlib.sha256("|".join(signature_parts).encode("utf-8")).hexdigest()
print(",".join(reasons) + "|" + signature)
PY
}

restart_dead_loops() {
  [[ "$MODULATOR_RESTART_LOOPS" == "1" ]] || return 0
  local reasons="$1"
  if [[ ",$reasons," == *",worker_loop_dead_with_work,"* ]]; then
    echo "$(utc_now) modulator restarting dead worker loop"
    rm -rf .ai/supervisor_runs/worker_loop.lock 2>/dev/null || true
    nohup bash scripts/worker_loop.sh >>.ai/supervisor_runs/worker_loop.log 2>&1 &
    echo "$!" >.ai/supervisor_runs/worker_loop.pid
    record_event --kind repair --role modulator \
      --reason-code worker_loop_restarted \
      --reason "modulator restarted dead worker loop" \
      --state running || true
  fi
  if [[ ",$reasons," == *",supervisor_loop_dead_with_work,"* ]]; then
    echo "$(utc_now) modulator restarting dead supervisor loop"
    rm -rf .ai/supervisor_runs/supervisor_loop.lock 2>/dev/null || true
    nohup bash scripts/supervisor_loop.sh >>.ai/supervisor_runs/supervisor_loop.log 2>&1 &
    echo "$!" >.ai/supervisor_runs/supervisor_loop.pid
    record_event --kind repair --role modulator \
      --reason-code supervisor_loop_restarted \
      --reason "modulator restarted dead supervisor loop" \
      --state running || true
  fi
}

run_modulator_agent() {
  local reasons="$1"
  local timestamp log_file prompt_file metrics_file started_at finished_at
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  log_file="$MODULATOR_RUNS_DIR/modulator.$timestamp.log"
  prompt_file="$MODULATOR_RUNS_DIR/modulator.$timestamp.prompt.md"
  metrics_file=".ai/metrics/modulator/modulator.$timestamp.metrics.json"

  set +e
  started_at="$(utc_now)"
  {
    echo "Wake reasons: $reasons"
    echo "Runtime option: MODULATOR_CLEARS_PRESET_BOUNDARIES=$MODULATOR_CLEARS_PRESET_BOUNDARIES"
    echo "workflow_commit=$workflow_commit"
    echo
    cat <<'PROMPT'
You are the always-on workflow modulator agent for this repository.

Read first:
- `.ai/supervisor/modulator_protocol.md` (your full protocol and authority limits)
- `AGENTS.md` (roles overview, including the Modulator section)
- `.ai/supervisor/autonomous_boundary_policy.md` (which gates you may and may not clear)
- `.ai/supervisor/ROOT_CAUSE_PRIORITY_LOCK.md`, if present
- `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md`, if present
- `.ai/supervisor/SUPERVISOR_ACTION_REQUIRED.md`, if present
- `.ai/supervisor/ledger.md` (recent tail)
- `.ai/supervisor/design_prompt.md` and `.ai/supervisor/roadmap.md` for the main target when auditing progress
- Job status/artifacts under `.ai/jobs/` relevant to the wake reasons above

Act strictly within the modulator protocol:
- Triage the wake reasons listed at the top of this prompt. Write one triage
  record to `.ai/modulator/triage/triage.<UTC timestamp>.md` summarizing what
  you inspected and decided.
- You own ALL failure handling between preset boundary gates. This includes
  technical blockers AND scope/architecture/scientific-convention decisions
  that arise mid-tranche: investigate, decide, and keep the workflow moving.
  Only preset boundary gates listed in
  `.ai/supervisor/autonomous_boundary_policy.md` wait for a human (unless the
  runtime option MODULATOR_CLEARS_PRESET_BOUNDARIES shown above is 1).
- For an open human gate caused by a technical blocker (failing test,
  unexplained numerical result, suspected code bug, repeated mechanical worker
  failure): investigate the actual code and evidence yourself. Read the
  relevant source files and job artifacts; reproduce numerically with
  read-only probes (for example a standalone python3 calculation in /tmp)
  when feasible. If and only if you identify a concrete root cause with
  verifiable evidence and the fix fits the currently delegated scope, write
  `.ai/supervisor/MODULATOR_FINDINGS.md` following the Findings Contract
  (Trigger / Diagnosis / Classification / Corrective Directive / Gate Action),
  move the gate file to `.ai/modulator/archive/HUMAN_REVIEW_REQUIRED.<UTC
  timestamp>.md`, and stop. The supervisor will dispatch the corrective job.
- For an open non-preset gate that asks for a scope, architecture, or
  scientific-convention decision: make the decision yourself. Ground it in
  the design prompt, the roadmap target (stable controlled BBH evolution),
  the cited public references, and the accepted evidence; choose the option
  that preserves scientific meaning and the smallest scope consistent with
  the roadmap. Record the decision with full rationale and references in
  `.ai/modulator/decisions/decision.<UTC timestamp>.md`, write
  `MODULATOR_FINDINGS.md` carrying the decision and its corrective/dispatch
  directive, archive the gate file, and stop. Do NOT leave such gates waiting
  for a human. Only escalate to a human if the decision would contradict an
  explicit prior human instruction or exceed the M32-M37 roadmap itself.
  When the decision changes the numerics of the scheme under test, the
  directive must instruct the supervisor to audit every frozen validation
  gate of the affected job for observability under the new scheme and to
  redesign dominated gates in the requeue amendment.
- If the gate is a preset boundary gate (pre-M32, pre-M33, pre-M35), leave it
  in place unless MODULATOR_CLEARS_PRESET_BOUNDARIES is 1. When leaving a
  gate in place, append a short `## Modulator Triage` note to the gate file
  with your independent verification so the human review is better informed,
  but do not alter the existing gate content.
- For `SUPERVISOR_ACTION_REQUIRED`, `worker_blocked:<job>`,
  `review_failed`/`review_timeout`, or
  repeated rejections: diagnose the failure mode from logs and artifacts. If
  it is a mechanical/workflow-state problem you can safely repair (stale lock,
  stale status file, missing directory), repair it and record the repair in
  your triage record. Otherwise write `MODULATOR_FINDINGS.md` with a
  corrective directive for the supervisor.
- For `worker_stalled:<jobs>`: the worker loop is alive but its log has not
  advanced for the configured stall window. Inspect the log tail, the job
  status, and the process tree (`ps -eo pid,ppid,etime,cmd`). Distinguish a
  legitimately long build/test (note it and stop) from a hung agent/command.
  For a genuine hang, kill the hung agent/test process group (never the loop
  itself), let the loop's stale-state recovery requeue the attempt, and
  record the repair; if the hang repeats at the same point, write
  `MODULATOR_FINDINGS.md` prescribing a job revision (e.g. split the test,
  add a timeout) for the supervisor.
- For `milestone_activity` or `mid_tranche_audit`: run the progress audit
  from the protocol. Compare accepted evidence against the design target
  (stable controlled BBH evolution, dual-frame first-order generalized
  harmonic, all-I3 cubed-sphere domain). Write
  `.ai/modulator/milestone_audits/<milestone-or-audit>.<UTC timestamp>.md`.
  Flag drift (proxy evidence labeled as evolution, audit-only chains,
  weakened validation, roadmap divergence) and, when supervisor action is
  needed, write `MODULATOR_FINDINGS.md`.
- For `human_steering`: read every unprocessed directive under
  `.ai/modulator/steering/` (oldest first). These are binding instructions
  from the human operator issued through the modulator terminal. Honor them:
  adjust your triage/decision behavior accordingly, write
  `MODULATOR_FINDINGS.md` if the supervisor must act, and record how each
  directive was honored in your triage record. Then move each processed file
  to `.ai/modulator/steering/processed/`.
- For `root_lock_violation`: read `.ai/supervisor/ROOT_CAUSE_PRIORITY_LOCK.md`
  and the violating post-lock job task/status files. If a queued or running job
  bypasses the locked root-cause path or lacks the required `## Upstream Trace`,
  write `MODULATOR_FINDINGS.md` directing the supervisor to supersede or stop
  that dispatch chain and return to the locked boundary-method path.
- Never edit `src/`, `tests/`, `CMakeLists.txt`, or supervisor-owned planning
  files. Never accept/reject/create jobs. Never loosen tolerances or waive
  reviewer blocks. Prescribe; do not implement.
- If `.ai/supervisor/MODULATOR_FINDINGS.md` already exists from a previous
  run, do not overwrite it; append a dated addendum section only if you have
  materially new evidence.

Finish with a concise summary: wake reasons handled, diagnosis (if any), gate
action taken, files written, and whether the supervisor or a human needs to
act next.
PROMPT
  } >"$prompt_file"
  local agent_exit stream_file=""
  if [[ "$MODULATOR_AGENT_WRAPPER" == "cursor-agent" ]]; then
    # stream-json gives exact token usage; the text converter keeps the log
    # human-readable for the GUI tail.
    stream_file="$MODULATOR_RUNS_DIR/modulator.$timestamp.stream.jsonl"
    python3 scripts/agent_wrapper.py run \
      --role modulator \
      --wrapper "$MODULATOR_AGENT_WRAPPER" \
      --model "$MODULATOR_MODEL" \
      --workspace "$ROOT" \
      --prompt-file "$prompt_file" \
      --output-format stream-json \
      --extra-args="$MODULATOR_EXTRA_ARGS" 2>>"$log_file" \
      | tee "$stream_file" \
      | python3 scripts/cursor_stream_to_text.py >>"$log_file"
    agent_exit=${PIPESTATUS[0]}
  else
    python3 scripts/agent_wrapper.py run \
      --role modulator \
      --wrapper "$MODULATOR_AGENT_WRAPPER" \
      --model "$MODULATOR_MODEL" \
      --workspace "$ROOT" \
      --prompt-file "$prompt_file" \
      --extra-args="$MODULATOR_EXTRA_ARGS" >"$log_file" 2>&1
    agent_exit=$?
  fi
  finished_at="$(utc_now)"
  set -e

  python3 scripts/collect_agent_metrics.py plain \
    --agent "$MODULATOR_AGENT_WRAPPER" \
    --role modulator \
    --run-id "modulator.$timestamp" \
    --model "$MODULATOR_MODEL" \
    --log "$log_file" \
    ${stream_file:+--stream "$stream_file"} \
    --started-at "$started_at" \
    --finished-at "$finished_at" \
    --exit-code "$agent_exit" \
    --output "$metrics_file" >/dev/null || true

  cat "$log_file"
  if [[ "$agent_exit" -ne 0 ]]; then
    echo "$(utc_now) modulator agent failed with exit $agent_exit; will retry on next wake signature change"
    record_event \
      --kind failure \
      --role modulator \
      --reason-code modulator_command_failed \
      --reason "modulator agent failed with exit code $agent_exit" \
      --state action_required \
      --path "$log_file" || true
  fi
  commit_workflow_records
  return 0
}

SIGNATURE_FILE="$MODULATOR_STATE_DIR/last_wake_signature"
last_signature="$(cat "$SIGNATURE_FILE" 2>/dev/null || echo "")"

while true; do
  state_line="$(wake_state)"
  reasons="${state_line%%|*}"
  signature="${state_line##*|}"

  if [[ -n "$reasons" && "$signature" != "$last_signature" ]]; then
    echo "$(utc_now) modulator wake: $reasons"
    restart_dead_loops "$reasons"
    agent_reasons="${reasons//worker_loop_dead_with_work/}"
    agent_reasons="${agent_reasons//supervisor_loop_dead_with_work/}"
    agent_reasons="$(echo "$agent_reasons" | sed 's/,,*/,/g; s/^,//; s/,$//')"
    if [[ -n "$agent_reasons" ]]; then
      run_modulator_agent "$agent_reasons"
    fi
    last_signature="$signature"
    printf '%s\n' "$last_signature" >"$SIGNATURE_FILE"
  fi

  sleep "$MODULATOR_POLL_SECONDS"
done
