#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

SUPERVISOR_POLL_SECONDS="${SUPERVISOR_POLL_SECONDS:-10}"
SUPERVISOR_RUNS_DIR="${SUPERVISOR_RUNS_DIR:-.ai/supervisor_runs}"
SUPERVISOR_VERBOSE="${SUPERVISOR_VERBOSE:-0}"
SUPERVISOR_AGENT_WRAPPER="${SUPERVISOR_AGENT_WRAPPER:-${CODEX_AGENT_WRAPPER:-codex}}"
CODEX_MODEL="${CODEX_MODEL:-gpt-5.5}"
CODEX_REASONING_EFFORT="${CODEX_REASONING_EFFORT:-high}"
CODEX_EXTRA_ARGS="${CODEX_EXTRA_ARGS:-}"
SUPERVISOR_AUTO_RELAUNCH_FAILURE="${SUPERVISOR_AUTO_RELAUNCH_FAILURE:-1}"
SUPERVISOR_MAX_FAILURE_RELAUNCHES="${SUPERVISOR_MAX_FAILURE_RELAUNCHES:-1}"
SUPERVISOR_PUSH_AFTER_STRUCTURAL_GATE="${SUPERVISOR_PUSH_AFTER_STRUCTURAL_GATE:-0}"
HUMAN_GATE=".ai/supervisor/HUMAN_REVIEW_REQUIRED.md"
STRUCTURAL_REQUEST=".ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md"
HUMAN_REVIEW_ACTION_REQUEST=".ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md"
SUPERVISOR_ACTION_REQUEST=".ai/supervisor/SUPERVISOR_ACTION_REQUIRED.md"
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

mkdir -p "$SUPERVISOR_RUNS_DIR"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOW_PACKAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export AI_WORKFLOW_PACKAGE_ROOT="${AI_WORKFLOW_PACKAGE_ROOT:-$WORKFLOW_PACKAGE_ROOT}"
workflow_commit="$(git -C "$SCRIPT_DIR/.." rev-parse --short HEAD 2>/dev/null || git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "workflow_commit=$workflow_commit"
echo "supervisor_agent_wrapper=$SUPERVISOR_AGENT_WRAPPER"
echo "supervisor_model=$CODEX_MODEL"
supervisor_failure_relaunches=0

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
    rm -f "$LOOP_LOCK/pid" "$LOOP_LOCK/started_at" 2>/dev/null || true
    rmdir "$LOOP_LOCK" 2>/dev/null || true
    LOOP_LOCK=""
  fi
}

acquire_loop_lock() {
  local lock_dir="$SUPERVISOR_RUNS_DIR/supervisor_loop.lock"
  if mkdir "$lock_dir" 2>/dev/null; then
    LOOP_LOCK="$lock_dir"
    printf '%s\n' "$$" >"$LOOP_LOCK/pid"
    date -u +"%Y-%m-%dT%H:%M:%SZ" >"$LOOP_LOCK/started_at"
    return 0
  fi
  if lock_pid_alive "$lock_dir"; then
    echo "supervisor_loop already running with pid $(cat "$lock_dir/pid" 2>/dev/null || echo unknown)"
    exit 0
  fi
  rm -f "$lock_dir/pid" "$lock_dir/started_at" 2>/dev/null || true
  rmdir "$lock_dir" 2>/dev/null || true
  if mkdir "$lock_dir" 2>/dev/null; then
    LOOP_LOCK="$lock_dir"
    printf '%s\n' "$$" >"$LOOP_LOCK/pid"
    date -u +"%Y-%m-%dT%H:%M:%SZ" >"$LOOP_LOCK/started_at"
    return 0
  fi
  echo "failed to acquire supervisor loop lock: $lock_dir" >&2
  exit 1
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

write_available_skills() {
  echo "Available skills visible to this supervisor run:"
  echo
  echo '```text'
  if ! python3 "$AI_WORKFLOW_PACKAGE_ROOT/scripts/list_skills.py" 2>/dev/null; then
    echo "Skill listing unavailable; inspect project skills/ and workflow package skills/ manually."
  fi
  echo '```'
  echo
  echo "When a skill is relevant, read the listed SKILL.md file before applying it. These repository skills are not assumed to be loaded by the Codex runtime automatically."
}

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
    if [[ -f "$HUMAN_REVIEW_ACTION_REQUEST" ]]; then
      echo "human_review_action_request:present:$(stat -c '%Y' "$HUMAN_REVIEW_ACTION_REQUEST" 2>/dev/null || true)"
    else
      echo "human_review_action_request:absent"
    fi
    if [[ -f "$SUPERVISOR_ACTION_REQUEST" ]]; then
      echo "supervisor_action_request:present:$(stat -c '%Y' "$SUPERVISOR_ACTION_REQUEST" 2>/dev/null || true)"
    else
      echo "supervisor_action_request:absent"
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
if Path(".ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md").exists():
    raise SystemExit(0)
if Path(".ai/supervisor/SUPERVISOR_ACTION_REQUIRED.md").exists():
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
if any(state in {"ready_for_review", "blocked", "review_failed", "review_timeout", "invalid"} for state in states):
    raise SystemExit(0)
if not any(state in {"queued", "running", "reviewing", "rejected", "implemented"} for state in states):
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
  local timestamp log_file prompt_file metrics_file supervisor_started_at supervisor_finished_at
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  log_file="$SUPERVISOR_RUNS_DIR/supervisor.$timestamp.log"
  prompt_file="$SUPERVISOR_RUNS_DIR/supervisor.$timestamp.prompt.md"
  metrics_file=".ai/metrics/supervisor/supervisor.$timestamp.metrics.json"

  set +e
  supervisor_started_at="$(utc_now)"
  {
    echo "Runtime option: SUPERVISOR_PUSH_AFTER_STRUCTURAL_GATE=$SUPERVISOR_PUSH_AFTER_STRUCTURAL_GATE"
    echo "workflow_commit=$workflow_commit"
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
- `.ai/supervisor/workflow_improvement_queue.md`, if present
- `.ai/supervisor/skill_decisions.md`, if present
- `.ai/supervisor/SUPERVISOR_ACTION_REQUIRED.md`, if present

PROMPT
    write_available_skills
    cat <<'PROMPT'

Rules:
- Do not implement scientific project code yourself.
- Worker implementation files live on the branch and isolated worktree named in each job's `status.json`; they are not expected to exist in the main worktree before acceptance.
- When reviewing a job, inspect `.worktrees/JNNNN/`, `git -C .worktrees/JNNNN ...`, job artifacts, commit docs, and the actual patch/diff. Do not fail review merely because worker-created files are absent from the main worktree.
- Use immutable `base_sha` from `status.json` for all worker diff comparisons, for example `git -C .worktrees/JNNNN diff base_sha..HEAD`. Treat `base_ref` as human-readable context only.
- Review jobs in `ready_for_review` according to the supervisor protocol.
- Treat jobs in `review_failed` or `review_timeout` as needing supervisor action; either rerun reviewers, reject with feedback, revise/supersede the job with a better-scoped task, or open a human gate only for unresolved human/scope/science decisions.
- A job in `implemented` or `reviewing` is still in the worker/reviewer pipeline. Do not review or modify it yet; wait for `ready_for_review`.
- For each `ready_for_review` job, inspect the worker report plus reviewer reports under `.ai/jobs/JNNNN/reviews/` when present.
- Check `changed_files.attempt-N.txt` and reviewer `diff_coverage` YAML blocks. If reviewers did not inspect every changed file, or if the diff is too large to review comprehensively, reject with actionable feedback to split the work or remove noisy/generated changes. Do not accept work based only on the worker report.
- Treat reviewer reports as advisory but important. If a reviewer recommends revision, either reject with actionable feedback or explicitly document why the concern is waived.
- Inspect the worker's Workflow Friction and Skill Suggestions sections and the reviewers' workflow-evolution assessments. Also inspect audit artifacts such as `attempt_consistency.attempt-N.md`, reviewer coverage reports, timeout logs, stale commit docs, and `feedback.md` for repeated workflow failure modes that the worker may not recognize.
- Run `python3 scripts/list_skills.py` before creating any new skill. Use the `attempt-artifact-consistency` skill when a retry or review involves contradictory worker reports, commit docs, job status, git history, changed-file lists, or test logs.
- Treat workflow evolution as reviewed change control: workers propose, reviewers assess, Codex supervisor deduplicates and decides. Do not let a worker-owned implementation job directly mutate workflow skills, templates, or supervisor protocols unless the job was explicitly a workflow-maintenance job.
- Record nontrivial workflow evolution proposals or decisions in `.ai/supervisor/workflow_improvement_queue.md` and `.ai/supervisor/skill_decisions.md`. You may use `python3 scripts/record_workflow_improvement.py` for consistent entries.
- Create a new skill only when it avoids real future duplication and does not overlap existing skills. Project-specific skills go under the project `skills/`; generally reusable scientific-coding workflow skills go under `external/ai-supervisor-worker-workflow/skills/` and require committing/pushing the workflow package plus updating the submodule pointer when possible.
- Prefer the smallest effective workflow change: ledger note, checklist/template update, protocol clarification, script fix, project doc, project-specific skill, then general reusable skill.
- Record skill and workflow-evolution decisions in `.ai/supervisor/ledger.md`, including created paths or reasons for deferring/rejecting suggestions.
- Accept or reject completed jobs based on report, tests, diffstat, comprehensive actual-diff review, and commit documentation.
- For ordinary revision requests, write concise actionable `feedback.md` and set state to `rejected` so the worker loop retries it.
- For terminal outcomes that must not be retried, set state to `superseded` or `cancelled`; do not use `rejected`.
- For accepted jobs, integrate the accepted worker branch into the main project history using a reviewable merge or cherry-pick strategy, set state to `accepted`, update the ledger, and record assumptions/risks.
- Before integrating a `ready_for_review` job, run `python3 scripts/integrate_job.py JNNNN` as a verification guard when available. If it passes and the main worktree is clean, use `python3 scripts/integrate_job.py JNNNN --apply` or an equivalent explicit Git integration command, then update status to `accepted`.
- If unrelated uncommitted main-worktree changes prevent integration, record the accepted/rejected decision and blocker, create `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md`, and do not create the next job.
- If the current milestone still has approved work remaining and no job is queued/running/rejected, create exactly one next small worker job.
- If a job is queued/running/rejected after your actions, stop with `WAITING_FOR_WORKER`.
- If repeated worker attempts fail for the same reason, first diagnose the concrete failure mode across attempts and revise the worker assignment accordingly when possible: update `feedback.md`, edit the active job task before requeueing, supersede it with a narrower replacement job, split it into smaller jobs, pre-stage allowed reference/context material, adjust validation instructions, or open `.ai/supervisor/SUPERVISOR_ACTION_REQUIRED.md` for an operational workflow repair. Record the diagnosis and chosen correction in the ledger/status. Use a human gate only when the blocker is an unresolved human, scope, architecture, or scientific decision Codex cannot safely make.
- If the milestone is complete, blocked after the failure-mode revision check, or needs a human scope/science decision, create or update `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md` using `.ai/supervisor/milestone_review_template.md`.
- The human gate must include a milestone summary, a `## Human Review To-Do List` section with `- [ ]` checklist items, and instructions to run `python3 scripts/human_milestone_review.py`.
- At milestone gates, include a short Workflow Evolution section summarizing accepted/deferred/rejected workflow-friction and skill-suggestion decisions since the last gate.
- Do not create a new worker job after creating a human gate.
- Keep human input at milestone boundaries, not individual jobs or commits.
- Supervisor planning files are supervisor-owned. Do not create a Cursor worker job whose objective is to edit `.ai/supervisor/roadmap.md`, `.ai/supervisor/project_brief.md`, `.ai/supervisor/ledger.md`, build/dependency policy, or milestone sequencing.
- If `.ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md` exists, handle it yourself as supervisor: read it plus the referenced human review/gate records, update roadmap/project brief/ledger/policy/job sequencing as needed, create `.ai/supervisor/HUMAN_REVIEW_REQUIRED.md` summarizing the revised plan and to-do list, archive or remove `STRUCTURAL_CHANGE_REQUESTED.md`, commit workflow records, and stop without dispatching a worker job.
- If `.ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md` exists, handle it yourself as supervisor before any worker sees the concern: read it plus the referenced human review/gate records, classify each failed review item as implementation revision, test/validation revision, documentation revision, planning/scope revision, or human clarification. Then either create exactly one small worker job with a closed-form task, update supervisor-owned planning records and open a new human gate, or open a human clarification gate. Archive or remove `HUMAN_REVIEW_ACTION_REQUESTED.md` only after the next worker job or human gate exists, commit workflow records, and stop. Do not pass the raw failed checklist directly to Cursor.
- If `.ai/supervisor/SUPERVISOR_ACTION_REQUIRED.md` exists, treat it as an operational supervisor action request, not a human milestone gate. Read the file and referenced logs, repair the workflow state if safe, rerun reviewer or integration steps if needed, update ledger/events, archive or remove the action request once resolved, and only open a human gate if there is a genuine milestone, scope, or scientific decision the supervisor cannot make.
- If an older worker-created major structural revision job is `ready_for_review`, treat the worker report as advisory only. Do not integrate worker-owned roadmap/project-brief/ledger edits. Prefer rejecting it as superseded by supervisor-owned structural planning, then perform the structural planning update yourself if the request remains unresolved.
- After creating the structural revision human gate, do not dispatch the next implementation job. Stop at the new human review gate so the human can approve the revised plan.
- If the runtime option `SUPERVISOR_PUSH_AFTER_STRUCTURAL_GATE` shown above is `1`, and after creating the structural revision review gate the main branch has a configured remote, commit workflow records as needed and push the updated main branch. If push fails, record the failure in the ledger and leave the human gate in place.
- Use the available project/workflow skills listed above when relevant. If a skill is relevant, open its `SKILL.md` and follow it.

Return a concise summary of what you reviewed, accepted/rejected/dispatched, and whether the workflow is waiting for worker or human review.
PROMPT
  } >"$prompt_file"
  python3 scripts/agent_wrapper.py run \
    --role supervisor \
    --wrapper "$SUPERVISOR_AGENT_WRAPPER" \
    --model "$CODEX_MODEL" \
    --workspace "$ROOT" \
    --prompt-file "$prompt_file" \
    --reasoning-effort "$CODEX_REASONING_EFFORT" \
    --extra-args="$CODEX_EXTRA_ARGS" >"$log_file" 2>&1
  local codex_exit=$?
  supervisor_finished_at="$(utc_now)"
  set -e

  python3 scripts/collect_agent_metrics.py codex \
    --role supervisor \
    --run-id "supervisor.$timestamp" \
    --model "$CODEX_MODEL" \
    --reasoning-effort "$CODEX_REASONING_EFFORT" \
    --log "$log_file" \
    --started-at "$supervisor_started_at" \
    --finished-at "$supervisor_finished_at" \
    --exit-code "$codex_exit" \
    --output "$metrics_file" >/dev/null || true

  cat "$log_file"
  if [[ "$codex_exit" -ne 0 ]]; then
    if [[ "$SUPERVISOR_AUTO_RELAUNCH_FAILURE" == "1" && "$supervisor_failure_relaunches" -lt "$SUPERVISOR_MAX_FAILURE_RELAUNCHES" ]]; then
      supervisor_failure_relaunches=$((supervisor_failure_relaunches + 1))
      echo "Relaunching Codex supervisor after exit $codex_exit (retry $supervisor_failure_relaunches/$SUPERVISOR_MAX_FAILURE_RELAUNCHES)"
      run_codex_supervisor
      return $?
    fi
    {
      echo "# Supervisor Action Required"
      echo
      echo "## Status"
      echo
      echo "supervisor_command_failed"
      echo
      echo "## Summary"
      echo
      echo "The autonomous Codex supervisor command failed with exit code $codex_exit after configured relaunch attempts."
      echo
      echo "## Required supervisor action"
      echo
      echo "- Inspect $log_file."
      echo "- Recover any partially updated job state if needed."
      echo "- Continue autonomous workflow if the failure is operational."
      echo "- Open a human milestone gate only for unresolved scope, scientific, or architecture decisions."
    } >"$SUPERVISOR_ACTION_REQUEST"
    record_event \
      --kind failure \
      --role supervisor \
      --reason-code supervisor_command_failed \
      --reason "Codex supervisor failed with exit code $codex_exit" \
      --state action_required \
      --path "$log_file" \
      --path "$SUPERVISOR_ACTION_REQUEST"
    commit_workflow_records
    echo "SUPERVISOR_ACTION_REQUIRED: $SUPERVISOR_ACTION_REQUEST"
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
