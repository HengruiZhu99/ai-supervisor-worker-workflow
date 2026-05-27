#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

SUPERVISOR_POLL_SECONDS="${SUPERVISOR_POLL_SECONDS:-10}"
SUPERVISOR_RUNS_DIR="${SUPERVISOR_RUNS_DIR:-.ai/supervisor_runs}"
CODEX_MODEL="${CODEX_MODEL:-}"
CODEX_EXTRA_ARGS="${CODEX_EXTRA_ARGS:-}"
HUMAN_GATE=".ai/supervisor/HUMAN_REVIEW_REQUIRED.md"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

for cmd in git codex python3; do
  require_command "$cmd"
done

mkdir -p "$SUPERVISOR_RUNS_DIR"

job_signature() {
  {
    if [[ -f "$HUMAN_GATE" ]]; then
      echo "human_gate:present"
    else
      echo "human_gate:absent"
    fi
    find .ai/jobs -path '.ai/jobs/J*/status.json' -type f -printf '%p:%T@\n' 2>/dev/null | sort || true
  } | python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
}

has_actionable_state() {
  python3 - <<'PY'
import json
from pathlib import Path

jobs_dir = Path(".ai/jobs")
states = []
for status_path in sorted(jobs_dir.glob("J*/status.json")):
    try:
        states.append(json.loads(status_path.read_text(encoding="utf-8")).get("state", ""))
    except Exception:
        states.append("invalid")

if not states:
    raise SystemExit(0)
if any(state in {"ready_for_review", "blocked", "invalid"} for state in states):
    raise SystemExit(0)
if not any(state in {"queued", "running", "rejected"} for state in states):
    raise SystemExit(0)
raise SystemExit(1)
PY
}

run_codex_supervisor() {
  local timestamp log_file
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  log_file="$SUPERVISOR_RUNS_DIR/supervisor.$timestamp.log"

  local model_args=()
  if [[ -n "$CODEX_MODEL" ]]; then
    model_args=(-m "$CODEX_MODEL")
  fi

  set +e
  {
    cat <<'PROMPT'
You are Codex running as the autonomous milestone-gated supervisor for this repository.

Read:
- `AGENTS.md`
- `.ai/supervisor/supervisor_protocol.md`
- `.ai/supervisor/design_prompt.md`
- `.ai/supervisor/project_brief.md`
- `.ai/supervisor/roadmap.md`
- `.ai/supervisor/ledger.md`
- `.ai/supervisor/review_checklist.md`
- `.ai/supervisor/commit_policy.md`

Rules:
- Do not implement scientific project code yourself.
- Review jobs in `ready_for_review` according to the supervisor protocol.
- Accept or reject completed jobs based on report, tests, diffstat, selected patch context, and commit documentation.
- For rejected jobs, write concise actionable `feedback.md` and set state to `rejected`.
- For accepted jobs, set state to `accepted`, update the ledger, and record assumptions/risks.
- If the current milestone still has approved work remaining and no job is queued/running/rejected, create exactly one next small worker job.
- If a job is queued/running/rejected after your actions, stop with `WAITING_FOR_WORKER`.
- If the milestone is complete, blocked, or needs a human scope/science decision, create or update `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md` using `.ai/supervisor/milestone_review_template.md`, do not create a new worker job, and stop.
- Keep human input at milestone boundaries, not individual jobs or commits.
- Use skills under `skills/` when relevant.

Return a concise summary of what you reviewed, accepted/rejected/dispatched, and whether the workflow is waiting for worker or human review.
PROMPT
  } | codex --ask-for-approval never --sandbox danger-full-access exec -C "$ROOT" "${model_args[@]}" $CODEX_EXTRA_ARGS - >"$log_file" 2>&1
  local codex_exit=$?
  set -e

  cat "$log_file"
  if [[ "$codex_exit" -ne 0 ]]; then
    {
      echo "# Human Milestone Review"
      echo
      echo "## Status"
      echo
      echo "blocked"
      echo
      echo "## Summary"
      echo
      echo "The autonomous Codex supervisor command failed with exit code $codex_exit."
      echo
      echo "## Risks requiring human decision"
      echo
      echo "- Inspect $log_file and decide whether to rerun the supervisor loop or intervene manually."
    } >"$HUMAN_GATE"
    echo "HUMAN_REVIEW_REQUIRED: $HUMAN_GATE"
    return "$codex_exit"
  fi
}

last_signature=""
ran_initial=0

while true; do
  if [[ -f "$HUMAN_GATE" ]]; then
    echo "HUMAN_REVIEW_REQUIRED: $HUMAN_GATE"
    exit 0
  fi

  signature="$(job_signature)"

  if [[ "$signature" != "$last_signature" || "$ran_initial" -eq 0 ]]; then
    if has_actionable_state; then
      run_codex_supervisor
      ran_initial=1
      last_signature="$(job_signature)"
    else
      last_signature="$signature"
    fi
  fi

  sleep "$SUPERVISOR_POLL_SECONDS"
done
