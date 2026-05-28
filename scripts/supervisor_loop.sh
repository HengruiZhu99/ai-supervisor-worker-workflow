#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

SUPERVISOR_POLL_SECONDS="${SUPERVISOR_POLL_SECONDS:-10}"
SUPERVISOR_RUNS_DIR="${SUPERVISOR_RUNS_DIR:-.ai/supervisor_runs}"
SUPERVISOR_VERBOSE="${SUPERVISOR_VERBOSE:-0}"
CODEX_MODEL="${CODEX_MODEL:-gpt-5.5}"
CODEX_REASONING_EFFORT="${CODEX_REASONING_EFFORT:-high}"
CODEX_EXTRA_ARGS="${CODEX_EXTRA_ARGS:-}"
SUPERVISOR_PUSH_AFTER_STRUCTURAL_GATE="${SUPERVISOR_PUSH_AFTER_STRUCTURAL_GATE:-0}"
HUMAN_GATE=".ai/supervisor/HUMAN_REVIEW_REQUIRED.md"
STRUCTURAL_REQUEST=".ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md"

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

commit_workflow_records() {
  python3 scripts/commit_workflow_records.py --message "workflow: record supervisor state" || true
}

job_signature() {
  {
    if [[ -f "$HUMAN_GATE" ]]; then
      echo "human_gate:present"
    else
      echo "human_gate:absent"
    fi
    if [[ -f "$STRUCTURAL_REQUEST" ]]; then
      echo "structural_request:present:$(stat -c '%Y' "$STRUCTURAL_REQUEST" 2>/dev/null || true)"
    else
      echo "structural_request:absent"
    fi
    find .ai/jobs -path '.ai/jobs/J*/status.json' -type f -printf '%p:%T@\n' 2>/dev/null | sort || true
  } | python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
}

has_actionable_state() {
  python3 - <<'PY'
import json
from pathlib import Path

if Path(".ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md").exists():
    raise SystemExit(0)

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
if not any(state in {"queued", "running", "reviewing", "rejected"} for state in states):
    raise SystemExit(0)
raise SystemExit(1)
PY
}

print_waiting_status() {
  if [[ "$SUPERVISOR_VERBOSE" != "1" ]]; then
    return 0
  fi

  python3 - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path

now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
parts = []
for status_path in sorted(Path(".ai/jobs").glob("J*/status.json")):
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception as exc:
        parts.append(f"{status_path.parent.name}:invalid({exc})")
        continue
    job_id = data.get("id") or status_path.parent.name
    state = data.get("state", "unknown")
    attempt = data.get("attempt", "")
    if attempt != "":
        parts.append(f"{job_id}:{state}:attempt-{attempt}")
    else:
        parts.append(f"{job_id}:{state}")

if parts:
    print(f"{now} supervisor waiting; jobs: " + ", ".join(parts), flush=True)
else:
    print(f"{now} supervisor waiting; no jobs found", flush=True)
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

  local config_args=()
  if [[ -n "$CODEX_REASONING_EFFORT" ]]; then
    config_args=(-c "model_reasoning_effort=\"$CODEX_REASONING_EFFORT\"")
  fi

  set +e
  {
    echo "Runtime option: SUPERVISOR_PUSH_AFTER_STRUCTURAL_GATE=$SUPERVISOR_PUSH_AFTER_STRUCTURAL_GATE"
    echo
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
- Worker implementation files live on the branch and isolated worktree named in each job's `status.json`; they are not expected to exist in the main worktree before acceptance.
- When reviewing a job, inspect `.worktrees/JNNNN/`, `git -C .worktrees/JNNNN ...`, job artifacts, commit docs, and the actual patch/diff. Do not fail review merely because worker-created files are absent from the main worktree.
- Review jobs in `ready_for_review` according to the supervisor protocol.
- A job in `reviewing` is still in the worker/reviewer pipeline. Do not review or modify it yet; wait for `ready_for_review`.
- For each `ready_for_review` job, inspect the worker report plus reviewer reports under `.ai/jobs/JNNNN/reviews/` when present.
- Check that reviewer reports include comprehensive actual-diff coverage. If reviewers did not inspect every changed file, or if the diff is too large to review comprehensively, reject with actionable feedback to split the work or remove noisy/generated changes. Do not accept work based only on the worker report.
- Treat reviewer reports as advisory but important. If a reviewer recommends revision, either reject with actionable feedback or explicitly document why the concern is waived.
- Inspect the worker's Skill Suggestions section and the reviewers' skill-suggestion assessments. Run `python3 scripts/list_skills.py` before creating any new skill.
- Create a new skill only when it avoids real future duplication and does not overlap existing skills. Project-specific skills go under the project `skills/`; generally reusable scientific-coding workflow skills go under `external/ai-supervisor-worker-workflow/skills/` and require committing/pushing the workflow package plus updating the submodule pointer when possible.
- Record skill decisions in `.ai/supervisor/ledger.md`, including paths created or reasons for deferring/rejecting suggestions.
- Accept or reject completed jobs based on report, tests, diffstat, comprehensive actual-diff review, and commit documentation.
- For rejected jobs, write concise actionable `feedback.md` and set state to `rejected`.
- For accepted jobs, integrate the accepted worker branch into the main project history using a reviewable merge or cherry-pick strategy, set state to `accepted`, update the ledger, and record assumptions/risks.
- If unrelated uncommitted main-worktree changes prevent integration, record the accepted/rejected decision and blocker, create `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md`, and do not create the next job.
- If the current milestone still has approved work remaining and no job is queued/running/rejected, create exactly one next small worker job.
- If a job is queued/running/rejected after your actions, stop with `WAITING_FOR_WORKER`.
- If the milestone is complete, blocked, or needs a human scope/science decision, create or update `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md` using `.ai/supervisor/milestone_review_template.md`.
- The human gate must include a milestone summary, a `## Human Review To-Do List` section with `- [ ]` checklist items, and instructions to run `python3 scripts/human_milestone_review.py`.
- Do not create a new worker job after creating a human gate.
- Keep human input at milestone boundaries, not individual jobs or commits.
- Supervisor planning files are supervisor-owned. Do not create a Cursor worker job whose objective is to edit `.ai/supervisor/roadmap.md`, `.ai/supervisor/project_brief.md`, `.ai/supervisor/ledger.md`, build/dependency policy, or milestone sequencing.
- If `.ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md` exists, handle it yourself as supervisor: read it plus the referenced human review/gate records, update roadmap/project brief/ledger/policy/job sequencing as needed, create `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md` summarizing the revised plan and to-do list, archive or remove `STRUCTURAL_CHANGE_REQUESTED.md`, commit workflow records, and stop without dispatching a worker job.
- If an older worker-created major structural revision job is `ready_for_review`, treat the worker report as advisory only. Do not integrate worker-owned roadmap/project-brief/ledger edits. Prefer rejecting it as superseded by supervisor-owned structural planning, then perform the structural planning update yourself if the request remains unresolved.
- After creating the structural revision human gate, do not dispatch the next implementation job. Stop at the new human review gate so the human can approve the revised plan.
- If the runtime option `SUPERVISOR_PUSH_AFTER_STRUCTURAL_GATE` shown above is `1`, and after creating the structural revision review gate the main branch has a configured remote, commit workflow records as needed and push the updated main branch. If push fails, record the failure in the ledger and leave the human gate in place.
- Use skills under `skills/` when relevant.

Return a concise summary of what you reviewed, accepted/rejected/dispatched, and whether the workflow is waiting for worker or human review.
PROMPT
  } | codex --ask-for-approval never --sandbox danger-full-access exec -C "$ROOT" "${model_args[@]}" "${config_args[@]}" $CODEX_EXTRA_ARGS - >"$log_file" 2>&1
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
    commit_workflow_records
    echo "HUMAN_REVIEW_REQUIRED: $HUMAN_GATE"
    return "$codex_exit"
  fi

  commit_workflow_records
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
      print_waiting_status
      last_signature="$signature"
    fi
  else
    print_waiting_status
  fi

  sleep "$SUPERVISOR_POLL_SECONDS"
done
