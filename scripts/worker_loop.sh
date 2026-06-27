#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOW_PACKAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export AI_WORKFLOW_PACKAGE_ROOT="${AI_WORKFLOW_PACKAGE_ROOT:-$WORKFLOW_PACKAGE_ROOT}"
cd "$ROOT"

# A zero timeout means the worker agent is allowed to run until it exits.
# Long refactor/reorganization jobs can legitimately exceed one hour. The
# legacy CURSOR_TIMEOUT environment variable may still be exported by existing
# launchers, so worker wall-clock limits are opt-in through WORKER_TIMEOUT or
# WORKER_AGENT_TIMEOUT instead.
WORKER_TIMEOUT="${WORKER_TIMEOUT:-${WORKER_AGENT_TIMEOUT:-0}}"
WORKER_AGENT_WRAPPER="${WORKER_AGENT_WRAPPER:-${CURSOR_AGENT_WRAPPER:-cursor-agent}}"
# Default worker model: Fable 1M high through the Cursor agent CLI.
WORKER_MODEL="${WORKER_MODEL:-${CURSOR_MODEL:-claude-fable-5-thinking-high}}"
WORKER_AGENT_EXTRA_ARGS="${WORKER_AGENT_EXTRA_ARGS:-${CURSOR_AGENT_EXTRA_ARGS:-}}"
CURSOR_OUTPUT_FORMAT="${CURSOR_OUTPUT_FORMAT:-stream-json}"
CURSOR_STREAM_PARTIAL_OUTPUT="${CURSOR_STREAM_PARTIAL_OUTPUT:-1}"
CURSOR_REVIEWERS_ENABLED="${CURSOR_REVIEWERS_ENABLED:-1}"
CURSOR_REVIEW_TIMEOUT="${CURSOR_REVIEW_TIMEOUT:-2400}"
REVIEWER_A_AGENT_WRAPPER="${REVIEWER_A_AGENT_WRAPPER:-${CURSOR_REVIEWER_A_WRAPPER:-cursor-agent}}"
REVIEWER_B_AGENT_WRAPPER="${REVIEWER_B_AGENT_WRAPPER:-${CURSOR_REVIEWER_B_WRAPPER:-cursor-agent}}"
REVIEWER_A_MODEL="${REVIEWER_A_MODEL:-${CURSOR_REVIEWER_A_MODEL:-claude-opus-4-7-thinking-high}}"
REVIEWER_B_MODEL="${REVIEWER_B_MODEL:-${CURSOR_REVIEWER_B_MODEL:-gpt-5.3-codex-high}}"
REVIEWER_AGENT_EXTRA_ARGS="${REVIEWER_AGENT_EXTRA_ARGS:-${CURSOR_REVIEWER_EXTRA_ARGS:-}}"
CURSOR_REVIEWER_MAX_RELAUNCHES="${CURSOR_REVIEWER_MAX_RELAUNCHES:-1}"
TEST_TIMEOUT="${TEST_TIMEOUT:-0}"
WORKER_AUTO_RESUME_TIMEOUT="${WORKER_AUTO_RESUME_TIMEOUT:-1}"
WORKER_MAX_TIMEOUT_RESUMES="${WORKER_MAX_TIMEOUT_RESUMES:-2}"
WORKER_AUTO_RELAUNCH_FAILURE="${WORKER_AUTO_RELAUNCH_FAILURE:-1}"
WORKER_MAX_FAILURE_RESUMES="${WORKER_MAX_FAILURE_RESUMES:-2}"
# Hard ceiling on TOTAL attempts per job (failure resumes, timeout resumes, and
# supervisor-driven `rejected` retries all increment the attempt counter). When
# the next attempt would exceed this, the job is escalated to `blocked` with a
# clear message instead of churning forever in a retry/rejection loop. Set to 0
# to disable the cap.
WORKER_MAX_ATTEMPTS="${WORKER_MAX_ATTEMPTS:-8}"
# Number of jobs the worker loop may process concurrently per scan. The default
# of 1 preserves the historical strictly-serial behavior exactly. Set >1 to let
# the supervisor dispatch a batch of independent jobs (each already runs in its
# own .worktrees/<id> worktree, ai/<id> branch, and per-job lock, so isolation
# is unchanged). Within a scan, up to this many jobs run in parallel and the
# loop waits for the whole batch before rescanning (so a job is never dispatched
# twice).
WORKER_MAX_PARALLEL_JOBS="${WORKER_MAX_PARALLEL_JOBS:-1}"
# Optional auto-integration: when set to 1, after the dispatch batch the loop
# integrates each ready_for_review job whose gates pass (integrate_job.py --apply
# enforces state, reviewer completion/blocks, attempt consistency, and a clean
# main worktree) and prunes its worktree/branch. Default 0 leaves integration to
# the supervisor/human, preserving current behavior.
WORKER_AUTO_INTEGRATE="${WORKER_AUTO_INTEGRATE:-0}"
WORKER_AUTO_INTEGRATE_METHOD="${WORKER_AUTO_INTEGRATE_METHOD:-merge}"
WORKER_INIT_SUBMODULES="${WORKER_INIT_SUBMODULES:-1}"
WORKER_SUBMODULE_PATHS="${WORKER_SUBMODULE_PATHS:-}"
WORKER_REQUIRED_SUBMODULE_PATHS="${WORKER_REQUIRED_SUBMODULE_PATHS:-}"
WORKER_CLEAN_UNDECLARED_SUBMODULES="${WORKER_CLEAN_UNDECLARED_SUBMODULES:-1}"
WORKER_ALLOW_SUBMODULE_CHANGES="${WORKER_ALLOW_SUBMODULE_CHANGES:-0}"
WORKER_RECOVER_STALE_RUNNING="${WORKER_RECOVER_STALE_RUNNING:-1}"
WORKER_RECOVER_LEGACY_STALE_LOCKS="${WORKER_RECOVER_LEGACY_STALE_LOCKS:-0}"
WORKER_RUNS_DIR="${WORKER_RUNS_DIR:-.ai/supervisor_runs}"
POLL_SECONDS="${POLL_SECONDS:-5}"
CURRENT_LOCK=""
LOOP_LOCK=""
HUMAN_GATE=".ai/supervisor/HUMAN_REVIEW_REQUIRED.md"
STRUCTURAL_REQUEST=".ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md"
HUMAN_REVIEW_ACTION_REQUEST=".ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md"
SUPERVISOR_ACTION_REQUEST=".ai/supervisor/SUPERVISOR_ACTION_REQUIRED.md"

normalize_cursor_model() {
  case "$1" in
    gpt-5.5)
      echo "gpt-5.5-high"
      ;;
    gpt-5.3-codex)
      echo "gpt-5.3-codex-high"
      ;;
    claude-opus-4.8-thinking-high)
      echo "claude-opus-4-8-thinking-high"
      ;;
    fable | fable-high | fable-1m-high)
      echo "claude-fable-5-thinking-high"
      ;;
    fable-xhigh | fable-1m-xhigh | fable-extra-high)
      echo "claude-fable-5-thinking-xhigh"
      ;;
    *)
      echo "$1"
      ;;
  esac
}

normalize_model_for_wrapper() {
  local wrapper="$1"
  local model="$2"
  if [[ "$wrapper" == "cursor-agent" ]]; then
    normalize_cursor_model "$model"
  else
    echo "$model"
  fi
}

WORKER_MODEL="$(normalize_model_for_wrapper "$WORKER_AGENT_WRAPPER" "$WORKER_MODEL")"
REVIEWER_A_MODEL="$(normalize_model_for_wrapper "$REVIEWER_A_AGENT_WRAPPER" "$REVIEWER_A_MODEL")"
REVIEWER_B_MODEL="$(normalize_model_for_wrapper "$REVIEWER_B_AGENT_WRAPPER" "$REVIEWER_B_MODEL")"
if [[ "$WORKER_AGENT_WRAPPER" == "cursor-agent" && -z "$WORKER_AGENT_EXTRA_ARGS" ]]; then
  WORKER_AGENT_EXTRA_ARGS="--force"
fi
if [[ "$REVIEWER_A_AGENT_WRAPPER" == "cursor-agent" && "$REVIEWER_B_AGENT_WRAPPER" == "cursor-agent" && -z "$REVIEWER_AGENT_EXTRA_ARGS" ]]; then
  REVIEWER_AGENT_EXTRA_ARGS="--force"
fi

cleanup_current_lock() {
  if [[ -n "${CURRENT_LOCK:-}" ]]; then
    rm -f "$CURRENT_LOCK/pid" "$CURRENT_LOCK/started_at" 2>/dev/null || true
    rmdir "$CURRENT_LOCK" 2>/dev/null || true
    CURRENT_LOCK=""
  fi
}

mark_current_lock_owned() {
  if [[ -n "${CURRENT_LOCK:-}" ]]; then
    printf '%s\n' "$$" >"$CURRENT_LOCK/pid"
    date -u +"%Y-%m-%dT%H:%M:%SZ" >"$CURRENT_LOCK/started_at"
  fi
}

stop_worker_loop() {
  cleanup_current_lock
  cleanup_loop_lock
  exit 143
}

interrupt_worker_loop() {
  cleanup_current_lock
  cleanup_loop_lock
  exit 130
}

cleanup_loop_lock() {
  if [[ -n "${LOOP_LOCK:-}" ]]; then
    rm -f "$LOOP_LOCK/pid" "$LOOP_LOCK/started_at" "$LOOP_LOCK/workflow_commit" 2>/dev/null || true
    rmdir "$LOOP_LOCK" 2>/dev/null || true
    LOOP_LOCK=""
  fi
}

cleanup_all_locks() {
  cleanup_current_lock
  cleanup_loop_lock
}

trap cleanup_all_locks EXIT
trap interrupt_worker_loop INT
trap stop_worker_loop TERM

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

for cmd in git jq python3 timeout; do
  require_command "$cmd"
done

workflow_commit="$(git -C "$SCRIPT_DIR/.." rev-parse --short HEAD 2>/dev/null || git rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [[ -z "$WORKER_SUBMODULE_PATHS" ]] &&
   git config --file .gitmodules --get-regexp '^submodule\..*\.path$' 2>/dev/null |
     awk '{print $2}' | grep -qx 'external/kokkos'; then
  WORKER_SUBMODULE_PATHS="external/kokkos"
fi
if [[ -z "$WORKER_REQUIRED_SUBMODULE_PATHS" && "$WORKER_SUBMODULE_PATHS" == *external/kokkos* ]]; then
  WORKER_REQUIRED_SUBMODULE_PATHS="external/kokkos"
fi
echo "workflow_commit=$workflow_commit"
echo "worker_agent_wrapper=$WORKER_AGENT_WRAPPER"
echo "worker_model=$WORKER_MODEL"
echo "worker_agent_extra_args=${WORKER_AGENT_EXTRA_ARGS:-<none>}"
echo "worker_submodule_paths=${WORKER_SUBMODULE_PATHS:-<all>}"
echo "worker_required_submodule_paths=${WORKER_REQUIRED_SUBMODULE_PATHS:-<none>}"
echo "reviewer_a_agent_wrapper=$REVIEWER_A_AGENT_WRAPPER"
echo "reviewer_a_model=$REVIEWER_A_MODEL"
echo "reviewer_b_agent_wrapper=$REVIEWER_B_AGENT_WRAPPER"
echo "reviewer_b_model=$REVIEWER_B_MODEL"
echo "reviewer_agent_extra_args=${REVIEWER_AGENT_EXTRA_ARGS:-<none>}"

write_available_skills() {
  local skill_root="${1:-$ROOT}"
  echo "## Available Skills"
  echo
  echo "These project and workflow skills are visible in this worktree. When a skill is relevant, read the listed SKILL.md file before applying it."
  echo
  echo '```text'
  if ! (cd "$skill_root" && python3 "$AI_WORKFLOW_PACKAGE_ROOT/scripts/list_skills.py") 2>/dev/null; then
    echo "Skill listing unavailable; fall back to inspecting project skills/ and workflow package skills/ manually."
  fi
  echo '```'
}

run_worker_agent() {
  local worktree="$1"
  local prompt_file="$2"

  local stream_args=()
  if [[ "$CURSOR_STREAM_PARTIAL_OUTPUT" == "1" ]]; then
    stream_args=(--stream-partial-output)
  fi
  local command=(
    python3 scripts/agent_wrapper.py run \
      --role worker \
      --wrapper "$WORKER_AGENT_WRAPPER" \
      --model "$WORKER_MODEL" \
      --workspace "$worktree" \
      --prompt-file "$prompt_file" \
      --output-format "$CURSOR_OUTPUT_FORMAT" \
      "${stream_args[@]}" \
      --extra-args="$WORKER_AGENT_EXTRA_ARGS"
  )
  if [[ "$WORKER_TIMEOUT" == "0" ]]; then
    "${command[@]}"
  else
    timeout "$WORKER_TIMEOUT" "${command[@]}"
  fi
}

run_reviewer_agent() {
  local worktree="$1"
  local prompt_file="$2"
  local wrapper="$3"
  local model="$4"

  local stream_args=()
  if [[ "$CURSOR_STREAM_PARTIAL_OUTPUT" == "1" ]]; then
    stream_args=(--stream-partial-output)
  fi
  timeout "$CURSOR_REVIEW_TIMEOUT" \
    python3 scripts/agent_wrapper.py run \
      --role reviewer \
      --wrapper "$wrapper" \
      --model "$model" \
      --workspace "$worktree" \
      --prompt-file "$prompt_file" \
      --output-format "$CURSOR_OUTPUT_FORMAT" \
      "${stream_args[@]}" \
      --extra-args="$REVIEWER_AGENT_EXTRA_ARGS"
}

update_status() {
  local status_file="$1"
  shift
  local allow_state=()
  local item
  for item in "$@"; do
    if [[ "$item" == state=* ]]; then
      allow_state=(--allow-state)
      break
    fi
  done
  python3 scripts/update_job_status.py "${allow_state[@]}" "$status_file" "$@" >/dev/null
}

run_progress_gate() {
  local job="$1"
  local status_file="$2"
  local task_file="$3"
  local attempt="$4"
  local log="$job/progress_gate.attempt-$attempt.log"
  local json="$job/progress_gate.attempt-$attempt.json"
  local stderr_log="$job/progress_gate.attempt-$attempt.stderr.log"
  local gate_exit=0

  python3 scripts/check_job_progress_gate.py "$task_file" --jobs-dir .ai/jobs --json >"$json" 2>"$stderr_log" || gate_exit=$?
  {
    if [[ -s "$stderr_log" ]]; then
      cat "$stderr_log"
      echo
    fi
    cat "$json" 2>/dev/null || true
  } >"$log"
  rm -f "$stderr_log"
  update_status "$status_file" progress_gate_log="$log" progress_gate_json="$json" progress_gate_exit="$gate_exit"
  if [[ "$gate_exit" -ne 0 ]]; then
    update_status "$status_file" state=blocked worker_error="job progress gate failed; see $log"
    return "$gate_exit"
  fi
  update_status "$status_file" --merge-status-fields "$json"
  return 0
}

json_field() {
  local status_file="$1"
  local field="$2"
  jq -r --arg field "$field" '.[$field] // ""' "$status_file"
}

attempt_still_active() {
  local status_file="$1"
  local id="$2"
  local attempt="$3"
  local phase="$4"
  shift 4

  local current_state current_attempt allowed_state
  current_state="$(jq -r '.state // ""' "$status_file" 2>/dev/null || echo invalid)"
  current_attempt="$(jq -r '.attempt // 0' "$status_file" 2>/dev/null || echo invalid)"

  if [[ "$current_attempt" == "$attempt" ]]; then
    for allowed_state in "$@"; do
      if [[ "$current_state" == "$allowed_state" ]]; then
        return 0
      fi
    done
  fi

  echo "Skipping stale $id attempt $attempt during $phase: status is state=$current_state attempt=$current_attempt" >&2
  return 1
}

utc_now() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

collect_cursor_metrics() {
  python3 scripts/collect_agent_metrics.py cursor "$@" >/dev/null || true
}

clean_worker_submodules() {
  local job="$1"
  local worktree="$2"
  local attempt="$3"
  local phase="$4"
  local allowed_submodules="$job/allowed_submodule_paths.txt"
  local log="$job/submodule_cleanliness.${phase}.attempt-$attempt.log"

  if [[ "$WORKER_CLEAN_UNDECLARED_SUBMODULES" != "1" || "$WORKER_ALLOW_SUBMODULE_CHANGES" == "1" ]]; then
    return 0
  fi
  if [[ ! -f "$worktree/.gitmodules" ]]; then
    return 0
  fi

  python3 scripts/clean_worker_submodules.py \
    --worktree "$worktree" \
    --phase "$phase" \
    --allowed-paths-file "$allowed_submodules" \
    --required-paths "$WORKER_REQUIRED_SUBMODULE_PATHS" \
    --output "$log" >/dev/null 2>&1 || true
}

lock_pid_alive() {
  local lock_dir="$1"
  local pid
  [[ -s "$lock_dir/pid" ]] || return 1
  pid="$(cat "$lock_dir/pid" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

acquire_loop_lock() {
  mkdir -p "$WORKER_RUNS_DIR"
  local lock_dir="$WORKER_RUNS_DIR/worker_loop.lock"
  if mkdir "$lock_dir" 2>/dev/null; then
    LOOP_LOCK="$lock_dir"
    printf '%s\n' "$$" >"$LOOP_LOCK/pid"
    date -u +"%Y-%m-%dT%H:%M:%SZ" >"$LOOP_LOCK/started_at"
    printf '%s\n' "$workflow_commit" >"$LOOP_LOCK/workflow_commit"
    return 0
  fi
  if lock_pid_alive "$lock_dir"; then
    echo "worker_loop already running with pid $(cat "$lock_dir/pid" 2>/dev/null || echo unknown)"
    exit 0
  fi
  clear_known_stale_lock "$lock_dir" || true
  if mkdir "$lock_dir" 2>/dev/null; then
    LOOP_LOCK="$lock_dir"
    printf '%s\n' "$$" >"$LOOP_LOCK/pid"
    date -u +"%Y-%m-%dT%H:%M:%SZ" >"$LOOP_LOCK/started_at"
    printf '%s\n' "$workflow_commit" >"$LOOP_LOCK/workflow_commit"
    return 0
  fi
  echo "failed to acquire worker loop lock: $lock_dir" >&2
  exit 1
}

clear_known_stale_lock() {
  local lock_dir="$1"
  rm -f "$lock_dir/pid" "$lock_dir/started_at" "$lock_dir/workflow_commit" 2>/dev/null || true
  rmdir "$lock_dir" 2>/dev/null
}

record_event() {
  python3 scripts/record_workflow_event.py "$@" >/dev/null 2>&1 || true
}

acquire_loop_lock

normalize_test_command() {
  local raw="$1"
  if [[ "$raw" == *\\n* ]]; then
    printf '%s' "${raw//\\n/$'\n'}"
  else
    printf '%s' "$raw"
  fi
}

recover_stale_running_jobs() {
  [[ "$WORKER_RECOVER_STALE_RUNNING" == "1" ]] || return 0

  local status_file job lock_dir state attempt commit report reason next_state
  shopt -s nullglob
  for status_file in .ai/jobs/J*/status.json; do
    state="$(jq -r '.state // ""' "$status_file")"
    [[ "$state" == "running" || "$state" == "reviewing" ]] || continue

    job="$(dirname "$status_file")"
    lock_dir="$job/.lock"
    reason=""

    if [[ -d "$lock_dir" ]]; then
      if lock_pid_alive "$lock_dir"; then
        continue
      fi
      if [[ -s "$lock_dir/pid" ]]; then
        reason="lock owner pid $(cat "$lock_dir/pid" 2>/dev/null || echo unknown) is not running"
      elif [[ "$WORKER_RECOVER_LEGACY_STALE_LOCKS" == "1" ]]; then
        reason="legacy lock has no owner pid"
      else
        continue
      fi
      if ! clear_known_stale_lock "$lock_dir"; then
        continue
      fi
    else
      reason="job is $state but has no lock directory"
    fi

    attempt="$(jq -r '.attempt // 0' "$status_file")"
    commit="$(json_field "$status_file" commit)"
    report="$(json_field "$status_file" report)"
    next_state="queued"
    if [[ "$attempt" != "0" && -n "$commit" && -n "$report" && -f "$report" ]]; then
      next_state="implemented"
    fi
    update_status "$status_file" \
      state="$next_state" \
      stale_recovered=true \
      worker_error="recovered stale $state job: $reason"
    echo "Recovered stale $state job $(basename "$job") as $next_state: $reason"
  done
  shopt -u nullglob
}

run_worker_preflight() {
  local job="$1"
  local status_file="$2"
  local id="$3"
  local attempt="$4"
  local worktree="$5"
  local branch="$6"
  local base_sha="$7"
  local starting_state="$8"
  local preflight_log="$job/preflight.attempt-$attempt.log"
  local preflight_exit=0
  local current_branch

  {
    echo "# Worker preflight for $id attempt $attempt"
    echo "workflow_commit=$workflow_commit"
    echo "worktree=$worktree"
    echo "branch=$branch"
    echo "base_sha=$base_sha"
    echo

    if ! git -C "$worktree" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      echo "ERROR: invalid Git worktree: $worktree"
      exit 10
    fi

    current_branch="$(git -C "$worktree" symbolic-ref --quiet --short HEAD || true)"
    echo "current_branch=$current_branch"
    if [[ "$current_branch" != "$branch" ]]; then
      echo "ERROR: current branch '$current_branch' does not match expected '$branch'"
      exit 11
    fi

    if ! git -C "$worktree" merge-base --is-ancestor "$base_sha" HEAD >/dev/null 2>&1; then
      echo "ERROR: base_sha is not an ancestor of worktree HEAD"
      exit 12
    fi

    echo
    echo "## Initial status"
    git -C "$worktree" status --short
    if [[ "$starting_state" != "rejected" && -n "$(git -C "$worktree" status --porcelain)" ]]; then
      echo "ERROR: worktree is dirty before a non-retry attempt"
      exit 13
    fi

    if [[ "$WORKER_INIT_SUBMODULES" == "1" && -f "$worktree/.gitmodules" ]]; then
      echo
      echo "## Submodule initialization"
      local submodule_exit=0
      if [[ -n "$WORKER_SUBMODULE_PATHS" ]]; then
        # shellcheck disable=SC2086
        git -C "$worktree" submodule update --init --recursive $WORKER_SUBMODULE_PATHS || submodule_exit=$?
      else
        git -C "$worktree" submodule update --init --recursive || submodule_exit=$?
      fi
      if [[ "$submodule_exit" -ne 0 ]]; then
        echo "WARNING: submodule update exited with status $submodule_exit."
        echo "Continuing unless WORKER_REQUIRED_SUBMODULE_PATHS declares a missing required path."
      fi
      git -C "$worktree" submodule status --recursive || true
    else
      echo
      echo "## Submodule initialization"
      echo "Skipped: WORKER_INIT_SUBMODULES=$WORKER_INIT_SUBMODULES or no .gitmodules file."
    fi

    if [[ -n "$WORKER_REQUIRED_SUBMODULE_PATHS" ]]; then
      echo
      echo "## Required submodule checks"
      local required_path missing_required=0
      for required_path in $WORKER_REQUIRED_SUBMODULE_PATHS; do
        if [[ ! -e "$worktree/$required_path" ]]; then
          echo "ERROR: required submodule path is missing after submodule initialization: $required_path"
          missing_required=1
        else
          echo "$required_path exists."
        fi
      done
      if [[ "$missing_required" -ne 0 ]]; then
        exit 14
      fi
    fi

    echo
    echo "Preflight passed."
  } >"$preflight_log" 2>&1 || preflight_exit=$?

  update_status "$status_file" preflight_log="$preflight_log" preflight_exit="$preflight_exit"
  if [[ "$preflight_exit" -ne 0 ]]; then
    update_status "$status_file" state=blocked worker_error="worker preflight failed; see $preflight_log"
    return "$preflight_exit"
  fi
  return 0
}

run_attempt_consistency_check() {
  local job="$1"
  local status_file="$2"
  local attempt="$3"
  local worktree="$4"
  local base_sha="$5"
  local final_commit="$6"
  local test_log="$7"
  local report="$8"
  local handoff_json="${9:-}"
  local out_file="$job/attempt_consistency.attempt-$attempt.md"
  local check_exit=0

  python3 scripts/check_attempt_consistency.py \
    --job "$job" \
    --status "$status_file" \
    --worktree "$worktree" \
    --attempt "$attempt" \
    --base-sha "$base_sha" \
    --commit "$final_commit" \
    --report "$report" \
    --test-log "$test_log" \
    --handoff-json "$handoff_json" \
    --output "$out_file" >/dev/null 2>&1 || check_exit=$?
  update_status "$status_file" attempt_consistency_log="$out_file" attempt_consistency_exit="$check_exit"
  return "$check_exit"
}

canonical_commit_doc_path() {
  local id="$1"
  local attempt="$2"
  local final_commit="$3"
  echo ".ai/commit_docs/${id}_attempt-${attempt}_${final_commit}.md"
}

write_reviewer_prompt() {
  local role="$1"
  local job="$2"
  local id="$3"
  local attempt="$4"
  local worktree="$5"
  local base_sha="$6"
  local final_commit="$7"
  local prompt_file="$8"
  local changed_files_file="$job/changed_files.attempt-$attempt.txt"
  local canonical_commit_doc
  local focus

  canonical_commit_doc="$(canonical_commit_doc_path "$id" "$attempt" "$final_commit")"

  if [[ "$role" == "reviewer-a" ]]; then
    focus="scientific and numerical correctness, mathematical assumptions, units/dimensions, tolerances, edge cases, validation quality, documentation of scientific meaning, and scope discipline"
  else
    focus="code quality, CMake/build behavior, tests, Git hygiene, Kokkos/MPI/OpenMP/SYCL portability, memory layout, race/rank/backend risks, and maintainability"
  fi

  {
    echo "# Cursor Reviewer Instructions"
    echo
    echo "You are $role for job $id attempt $attempt."
    echo
    echo "This is a read-only review. Do not edit files, create commits, change branches, or modify the worktree."
    echo "Focus on: $focus."
    echo
    echo "## Review Context"
    echo
    echo "- Worktree: $ROOT/$worktree"
    echo "- Base SHA: $base_sha"
    echo "- Final worker commit: $final_commit"
    echo "- Task: $ROOT/$job/task.md"
    echo "- Worker report: $ROOT/$job/report.md"
    echo "- Structured worker handoff: $ROOT/$job/worker_handoff.attempt-$attempt.json"
    echo "- Raw worker transcript, audit only: $ROOT/$job/cursor_final.attempt-$attempt.md"
    echo "- Diffstat: $ROOT/$job/diffstat.attempt-$attempt.txt"
    echo "- Changed files: $ROOT/$changed_files_file"
    echo "- Patch: $ROOT/$job/diff.attempt-$attempt.patch"
    echo "- Test log: $ROOT/$job/test.attempt-$attempt.log"
    echo "- Canonical current-attempt commit doc: $ROOT/$canonical_commit_doc"
    echo "- Commit docs directory: $ROOT/.ai/commit_docs/"
    echo "- Existing skills: run 'python3 scripts/list_skills.py' in the worktree if needed. The environment variable AI_WORKFLOW_PACKAGE_ROOT is set to $AI_WORKFLOW_PACKAGE_ROOT."
    echo
    write_available_skills "$ROOT/$worktree"
    echo
    echo "## Changed Files To Cover"
    echo
    if [[ -s "$changed_files_file" ]]; then
      sed 's/^/- /' "$changed_files_file"
    else
      echo "- No changed files were recorded."
    fi
    echo
    echo "Read the actual diff comprehensively, not just the worker report. Start from the diffstat, then inspect every changed file in the patch and/or worktree."
    echo "Treat the worker report and structured handoff as worker narrative. Treat status.json, changed_files, test logs, commit docs, and Git diff from base SHA to final commit as canonical. Do not rely on the raw transcript except when debugging an inconsistency."
    echo "Use the canonical current-attempt commit doc and $ROOT/$job/attempt_consistency.attempt-$attempt.md for the final attempt audit. If the worker branch also contains older .ai/commit_docs files, review them as historical evidence for the attempt/commit they name, not as required coverage for later bookkeeping commits."
    echo "Use commands such as 'git diff --name-only $base_sha..$final_commit', 'git diff $base_sha..$final_commit -- <path>', and direct source reads from the worktree."
    echo "If the diff is too large to review comprehensively within this reviewer pass, recommend revise/split; do not recommend acceptance for partially reviewed work."
    echo "Cross-check the worker report, test log, commit docs, and actual code. The actual diff and worktree are the source of truth."
    echo "Inspect the worker's Workflow Friction and Skill Suggestions sections. Treat them as proposals only. Decide whether each point is real, repeated, already covered by an existing skill/template/checklist/script, or too narrow to keep."
    echo "Inspect the task's Progress Classification. State whether the job adds executable behavior, numerical validation, backend validation, or credibly unblocks a named implementation/test job. If the job is metadata-like, assess whether accepting it would continue a metadata-only streak."
    echo
    echo "Include this machine-checkable fenced YAML block exactly once. Replace the template values with your actual review result:"
    echo '```yaml'
    echo "diff_coverage:"
    echo "  full_diff_reviewed: true"
    if [[ -s "$changed_files_file" ]]; then
      echo "  files_reviewed:"
      awk '
        NF == 0 { next }
        $1 ~ /^R/ && NF >= 3 { print "    - " $3; next }
        NF >= 2 { print "    - " $2 }
      ' "$changed_files_file"
    else
      echo "  files_reviewed: []"
    fi
    echo "  unreviewed_files: []"
    echo "review_decision:"
    echo "  recommendation: accept  # one of: accept, revise, needs-supervisor-judgment"
    echo "  blocks_acceptance: false"
    echo "  blocking_reasons: []"
    echo "progress_review:"
    echo "  adds_executable_or_validation_value: true"
    echo "  metadata_unlock_is_credible: true"
    echo "  continues_metadata_streak: false"
    echo "  blocks_acceptance: false"
    echo "  blocking_reasons: []"
    echo '```'
    echo
    echo "## Output Format"
    echo
    echo "Return a concise markdown report with:"
    echo "1. Recommendation: accept, revise, or needs-supervisor-judgment"
    echo "2. Blocking concerns"
    echo "3. Nonblocking concerns"
    echo "4. Evidence reviewed"
    echo "5. Diff coverage: list changed files reviewed, state whether the full diff was reviewed, and list any unreviewed paths. If any path was not reviewed, recommendation must not be accept."
    echo "6. Test and validation assessment"
    echo "7. Scope assessment"
    echo "8. Progress value assessment"
    echo "9. Suggested supervisor decision rationale"
    echo "10. Workflow friction review: which reported frictions are valid, whether they need a skill, template, script, protocol/checklist update, project documentation, or no action, and whether the issue appears one-off or recurring."
    echo "11. Skill suggestion review: whether the worker's suggested skills are useful, duplicate existing skills, and should be project-specific, general workflow skills, deferred, or rejected. Run 'python3 scripts/list_skills.py' if needed."
    echo "12. Workflow evolution recommendations: provide concise proposed queue entries for the supervisor, each with title, source, category (skill/template/script/protocol/checklist/docs/ledger), scope (project/general), rationale, and recommended decision (create/update/defer/reject)."
  } >"$prompt_file"
}

run_one_reviewer() {
  local role="$1"
  local wrapper="$2"
  local model="$3"
  local job="$4"
  local id="$5"
  local attempt="$6"
  local worktree="$7"
  local base_sha="$8"
  local final_commit="$9"
  local reviews_dir="$job/reviews"

  mkdir -p "$reviews_dir"

  local prompt_file="$reviews_dir/$role.prompt.attempt-$attempt.md"
  local review_out="$reviews_dir/$role.attempt-$attempt.md"
  local review_err="$reviews_dir/$role.stderr.attempt-$attempt.log"
  local review_stream="$reviews_dir/$role.stream.attempt-$attempt.jsonl"
  local review_metrics="$reviews_dir/$role.metrics.attempt-$attempt.json"
  local reviewer_exit=0
  local reviewer_started_at reviewer_finished_at

  write_reviewer_prompt "$role" "$job" "$id" "$attempt" "$worktree" "$base_sha" "$final_commit" "$prompt_file"

  set +e
  reviewer_started_at="$(utc_now)"
  if [[ "$CURSOR_OUTPUT_FORMAT" == "stream-json" ]]; then
    run_reviewer_agent "$ROOT/$worktree" "$ROOT/$prompt_file" "$wrapper" "$model" \
      2> >(tee "$review_err" >&2) \
      | tee "$review_stream" \
      | python3 "$SCRIPT_DIR/cursor_stream_to_text.py" \
      | tee "$review_out"
  else
    run_reviewer_agent "$ROOT/$worktree" "$ROOT/$prompt_file" "$wrapper" "$model" 2> >(tee "$review_err" >&2) | tee "$review_out"
  fi
  reviewer_exit=${PIPESTATUS[0]}
  reviewer_finished_at="$(utc_now)"
  set -e

  collect_cursor_metrics \
    --role reviewer \
    --reviewer-role "$role" \
    --job-id "$id" \
    --attempt "$attempt" \
    --model "$model" \
    --stream "$review_stream" \
    --stdout "$review_out" \
    --stderr "$review_err" \
    --started-at "$reviewer_started_at" \
    --finished-at "$reviewer_finished_at" \
    --exit-code "$reviewer_exit" \
    --output "$review_metrics"

  if [[ "$reviewer_exit" -eq 124 ]]; then
    echo "Reviewer $role timed out after ${CURSOR_REVIEW_TIMEOUT}s" | tee -a "$review_err" >&2
  elif [[ "$reviewer_exit" -ne 0 ]]; then
    echo "Reviewer $role exited with code $reviewer_exit" | tee -a "$review_err" >&2
  fi

  return "$reviewer_exit"
}

run_reviewer_with_retries() {
  local role="$1"
  local wrapper="$2"
  local model="$3"
  local job="$4"
  local id="$5"
  local attempt="$6"
  local worktree="$7"
  local base_sha="$8"
  local final_commit="$9"
  local exit_file="${10}"
  local try reviewer_exit

  reviewer_exit=0
  for ((try = 0; try <= CURSOR_REVIEWER_MAX_RELAUNCHES; try++)); do
    reviewer_exit=0
    run_one_reviewer "$role" "$wrapper" "$model" "$job" "$id" "$attempt" "$worktree" "$base_sha" "$final_commit" || reviewer_exit=$?
    [[ "$reviewer_exit" -eq 0 ]] && break
    if [[ "$try" -lt "$CURSOR_REVIEWER_MAX_RELAUNCHES" ]]; then
      echo "Relaunching $role after exit $reviewer_exit (retry $((try + 1))/${CURSOR_REVIEWER_MAX_RELAUNCHES})"
    fi
  done

  printf '%s\n' "$reviewer_exit" >"$exit_file"
  return 0
}

run_reviewers() {
  local job="$1"
  local status_file="$2"
  local id="$3"
  local attempt="$4"
  local worktree="$5"
  local base_sha="$6"
  local final_commit="$7"
  local reviewer_a_exit=0
  local reviewer_b_exit=0

  if ! attempt_still_active "$status_file" "$id" "$attempt" "review launch" running implemented ready_for_review; then
    return 125
  fi

  if [[ "$CURSOR_REVIEWERS_ENABLED" != "1" ]]; then
    update_status "$status_file" reviewers_enabled=false
    return 0
  fi

  update_status "$status_file" \
    state=reviewing \
    reviewers_enabled=true \
    reviewers_parallel=true \
    reviewers_complete=false \
    reviewer_a_exit=null \
    reviewer_b_exit=null \
    reviewer_coverage_exit=null \
    reviewer_decision_exit=null \
    reviewer_a_blocks=false \
    reviewer_b_blocks=false \
    reviewer_a_progress_blocks=false \
    reviewer_b_progress_blocks=false \
    reviewer_a_recommendation="" \
    reviewer_b_recommendation="" \
    review_blocked_by="" \
    reviewer_a_report="$job/reviews/reviewer-a.attempt-$attempt.md" \
    reviewer_b_report="$job/reviews/reviewer-b.attempt-$attempt.md" \
    reviewer_a_metrics="$job/reviews/reviewer-a.metrics.attempt-$attempt.json" \
    reviewer_b_metrics="$job/reviews/reviewer-b.metrics.attempt-$attempt.json" \
    reviewer_decision_file="$job/reviews/reviewer_decisions.attempt-$attempt.json" \
    reviewer_decision_log="$job/reviews/reviewer_decisions.attempt-$attempt.log" \
    reviewer_a_wrapper="$REVIEWER_A_AGENT_WRAPPER" \
    reviewer_b_wrapper="$REVIEWER_B_AGENT_WRAPPER" \
    reviewer_a_model="$REVIEWER_A_MODEL" \
    reviewer_b_model="$REVIEWER_B_MODEL"

  local reviews_dir="$job/reviews"
  local reviewer_a_exit_file="$reviews_dir/reviewer-a.exit.attempt-$attempt.txt"
  local reviewer_b_exit_file="$reviews_dir/reviewer-b.exit.attempt-$attempt.txt"
  local reviewer_decision_file="$reviews_dir/reviewer_decisions.attempt-$attempt.json"
  local reviewer_decision_log="$reviews_dir/reviewer_decisions.attempt-$attempt.log"
  local reviewer_a_pid reviewer_b_pid
  mkdir -p "$reviews_dir"
  rm -f "$reviewer_a_exit_file" "$reviewer_b_exit_file"

  echo "Launching reviewer-a and reviewer-b in parallel for $id attempt $attempt"
  run_reviewer_with_retries \
    "reviewer-a" "$REVIEWER_A_AGENT_WRAPPER" "$REVIEWER_A_MODEL" "$job" "$id" "$attempt" "$worktree" "$base_sha" "$final_commit" "$reviewer_a_exit_file" &
  reviewer_a_pid=$!
  run_reviewer_with_retries \
    "reviewer-b" "$REVIEWER_B_AGENT_WRAPPER" "$REVIEWER_B_MODEL" "$job" "$id" "$attempt" "$worktree" "$base_sha" "$final_commit" "$reviewer_b_exit_file" &
  reviewer_b_pid=$!

  wait "$reviewer_a_pid" || true
  wait "$reviewer_b_pid" || true

  reviewer_a_exit="$(cat "$reviewer_a_exit_file" 2>/dev/null || echo 1)"
  reviewer_b_exit="$(cat "$reviewer_b_exit_file" 2>/dev/null || echo 1)"

  if ! attempt_still_active "$status_file" "$id" "$attempt" "review finalization" reviewing; then
    return 125
  fi

  local coverage_exit=0
  python3 scripts/check_reviewer_coverage.py "$job/changed_files.attempt-$attempt.txt" \
    "$job/reviews/reviewer-a.attempt-$attempt.md" \
    "$job/reviews/reviewer-b.attempt-$attempt.md" \
    >"$job/reviews/coverage.attempt-$attempt.txt" 2>&1 || coverage_exit=$?

  local decision_exit=0
  python3 scripts/analyze_reviewer_reports.py \
    --reviewer-a "$job/reviews/reviewer-a.attempt-$attempt.md" \
    --reviewer-b "$job/reviews/reviewer-b.attempt-$attempt.md" \
    --output "$reviewer_decision_file" \
    >"$reviewer_decision_log" 2>&1 || decision_exit=$?

  local reviewer_a_blocks reviewer_b_blocks reviewer_blocked_by reviewer_a_recommendation reviewer_b_recommendation
  local reviewer_a_progress_blocks reviewer_b_progress_blocks
  reviewer_a_blocks="$(jq -r '.reviewer_a_blocks // false' "$reviewer_decision_file" 2>/dev/null || echo false)"
  reviewer_b_blocks="$(jq -r '.reviewer_b_blocks // false' "$reviewer_decision_file" 2>/dev/null || echo false)"
  reviewer_a_progress_blocks="$(jq -r '.reviewer_a_progress_blocks // false' "$reviewer_decision_file" 2>/dev/null || echo false)"
  reviewer_b_progress_blocks="$(jq -r '.reviewer_b_progress_blocks // false' "$reviewer_decision_file" 2>/dev/null || echo false)"
  reviewer_a_recommendation="$(jq -r '.reviewer_a_recommendation // "unknown"' "$reviewer_decision_file" 2>/dev/null || echo unknown)"
  reviewer_b_recommendation="$(jq -r '.reviewer_b_recommendation // "unknown"' "$reviewer_decision_file" 2>/dev/null || echo unknown)"
  reviewer_blocked_by="$(jq -r '(.blocked_by // []) | join(",")' "$reviewer_decision_file" 2>/dev/null || echo "")"
  local reviewer_decisions_complete
  reviewer_decisions_complete="$(jq -r '.reviewers_complete // false' "$reviewer_decision_file" 2>/dev/null || echo false)"

  update_status "$status_file" \
    reviewer_a_exit="$reviewer_a_exit" \
    reviewer_b_exit="$reviewer_b_exit" \
    reviewer_coverage_exit="$coverage_exit" \
    reviewer_decision_exit="$decision_exit" \
    reviewers_complete="$([[ "$reviewer_a_exit" -eq 0 && "$reviewer_b_exit" -eq 0 && "$coverage_exit" -eq 0 && "$reviewer_decisions_complete" == "true" ]] && echo true || echo false)" \
    reviewer_decision_file="$reviewer_decision_file" \
    reviewer_decision_log="$reviewer_decision_log" \
    reviewer_a_recommendation="$reviewer_a_recommendation" \
    reviewer_b_recommendation="$reviewer_b_recommendation" \
    reviewer_a_blocks="$reviewer_a_blocks" \
    reviewer_b_blocks="$reviewer_b_blocks" \
    reviewer_a_progress_blocks="$reviewer_a_progress_blocks" \
    reviewer_b_progress_blocks="$reviewer_b_progress_blocks" \
    review_blocked_by="$reviewer_blocked_by" \
    reviewer_a_report="$job/reviews/reviewer-a.attempt-$attempt.md" \
    reviewer_b_report="$job/reviews/reviewer-b.attempt-$attempt.md" \
    reviewer_a_metrics="$job/reviews/reviewer-a.metrics.attempt-$attempt.json" \
    reviewer_b_metrics="$job/reviews/reviewer-b.metrics.attempt-$attempt.json"

  if [[ "$reviewer_a_exit" -eq 124 || "$reviewer_b_exit" -eq 124 ]]; then
    return 124
  fi
  if [[ "$decision_exit" -ne 0 ]]; then
    record_event \
      --kind review_block \
      --role reviewer \
      --reason-code reviewer_recommended_revision \
      --reason "reviewer decision analysis blocked acceptance" \
      --job-id "$id" \
      --attempt "$attempt" \
      --state review_failed \
      --blocked-by "$reviewer_blocked_by" \
      --path "$reviewer_decision_file"
    return 1
  fi
  if [[ "$reviewer_a_exit" -ne 0 || "$reviewer_b_exit" -ne 0 || "$coverage_exit" -ne 0 ]]; then
    return 1
  fi
  return 0
}

process_job() {
  local job="$1"
  local status_file="$job/status.json"
  local lock_dir="$job/.lock"

  if ! mkdir "$lock_dir" 2>/dev/null; then
    return 0
  fi
  CURRENT_LOCK="$lock_dir"
  mark_current_lock_owned

  local id base_ref base_sha branch test_command attempt worktree current_branch starting_state
  id="$(json_field "$status_file" id)"
  base_ref="$(json_field "$status_file" base_ref)"
  base_sha="$(json_field "$status_file" base_sha)"
  branch="$(json_field "$status_file" branch)"
  test_command="$(json_field "$status_file" test_command)"
  test_command="$(normalize_test_command "$test_command")"
  attempt="$(jq -r '(.attempt // 0) + 1' "$status_file")"
  starting_state="$(jq -r '.state // ""' "$status_file")"
  worktree=".worktrees/$id"
  local task_file="$job/task.md"

  # Break infinite retry / repeated-rejection loops: once the next attempt would
  # exceed WORKER_MAX_ATTEMPTS, escalate to blocked instead of churning. This is
  # a no-op when WORKER_MAX_ATTEMPTS=0.
  if [[ "$WORKER_MAX_ATTEMPTS" != "0" && "$attempt" -gt "$WORKER_MAX_ATTEMPTS" ]]; then
    echo "ESCALATION: $id would start attempt $attempt > WORKER_MAX_ATTEMPTS=$WORKER_MAX_ATTEMPTS; blocking to break the retry loop"
    update_status "$status_file" \
      state=blocked \
      worker_error="reached WORKER_MAX_ATTEMPTS=$WORKER_MAX_ATTEMPTS without acceptance; escalated instead of looping (raise/clear WORKER_MAX_ATTEMPTS or reset attempt to retry)"
    record_event \
      --kind failure \
      --role worker \
      --reason-code attempt_cap_exceeded \
      --reason "attempt $attempt exceeded WORKER_MAX_ATTEMPTS=$WORKER_MAX_ATTEMPTS" \
      --job-id "$id" \
      --attempt "$attempt" \
      --state blocked \
      --path "$job" 2>/dev/null || true
    cleanup_current_lock
    return 0
  fi

  if [[ -z "$id" || -z "$base_ref" || -z "$branch" ]]; then
    update_status "$status_file" state=blocked worker_error="missing id, base_ref, or branch"
    cleanup_current_lock
    return 0
  fi
  if [[ ! -s "$task_file" ]]; then
    echo "Skipping $id: task file is not ready yet: $task_file"
    cleanup_current_lock
    return 0
  fi
  if ! run_progress_gate "$job" "$status_file" "$task_file" "$attempt"; then
    cleanup_current_lock
    return 0
  fi
  if [[ -z "$base_sha" ]]; then
    if ! base_sha="$(git rev-parse --verify "${base_ref}^{commit}")"; then
      update_status "$status_file" state=blocked worker_error="failed to resolve base_ref $base_ref"
      cleanup_current_lock
      return 0
    fi
    update_status "$status_file" base_sha="$base_sha"
  fi

  mkdir -p .worktrees
  if git -C "$worktree" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    current_branch="$(git -C "$worktree" symbolic-ref --quiet --short HEAD || true)"
    if [[ "$current_branch" != "$branch" ]]; then
      update_status "$status_file" state=blocked worker_error="existing worktree $worktree is on branch $current_branch, expected $branch"
      cleanup_current_lock
      return 0
    fi
  else
    if [[ -e "$worktree" ]]; then
      update_status "$status_file" state=blocked worker_error="worktree path exists but is not a valid Git worktree: $worktree"
      cleanup_current_lock
      return 0
    fi
    if git show-ref --verify --quiet "refs/heads/$branch"; then
      if ! git worktree add "$worktree" "$branch"; then
        update_status "$status_file" state=blocked worker_error="failed to create worktree $worktree from branch $branch"
        cleanup_current_lock
        return 0
      fi
    else
      if ! git rev-parse --verify "${base_sha}^{commit}" >/dev/null 2>&1; then
        update_status "$status_file" state=blocked worker_error="base_sha is not available in this checkout: $base_sha"
        cleanup_current_lock
        return 0
      fi
      if ! git worktree add -b "$branch" "$worktree" "$base_sha"; then
        update_status "$status_file" state=blocked worker_error="failed to create worktree $worktree from base_sha $base_sha"
        cleanup_current_lock
        return 0
      fi
    fi
  fi

  update_status "$status_file" \
    state=running \
    attempt="$attempt" \
    branch="$branch" \
    base_sha="$base_sha" \
    workflow_commit="$workflow_commit" \
    commit=null \
    commit_doc= \
    allowed_artifacts= \
    changed_files= \
    worker_metrics= \
    worker_handoff= \
    report= \
    worker_exit=null \
    worker_error= \
    test_exit=null \
    test_timed_out=false \
    tests_passed=false \
    timed_out=false \
    cursor_reported_success=false \
    attempt_consistency_exit=null \
    attempt_consistency_log= \
    post_test_dirty=false \
    post_test_status= \
    post_test_status_raw= \
    reviewers_complete=false \
    reviewer_a_exit=null \
    reviewer_b_exit=null \
    reviewer_coverage_exit=null \
    reviewer_decision_exit=null \
    reviewer_a_blocks=false \
    reviewer_b_blocks=false \
    reviewer_a_progress_blocks=false \
    reviewer_b_progress_blocks=false \
    reviewer_a_recommendation= \
    reviewer_b_recommendation= \
    review_blocked_by= \
    reviewer_a_report="$job/reviews/reviewer-a.attempt-$attempt.md" \
    reviewer_b_report="$job/reviews/reviewer-b.attempt-$attempt.md" \
    reviewer_a_metrics="$job/reviews/reviewer-a.metrics.attempt-$attempt.json" \
    reviewer_b_metrics="$job/reviews/reviewer-b.metrics.attempt-$attempt.json" \
    reviewer_decision_file="$job/reviews/reviewer_decisions.attempt-$attempt.json" \
    reviewer_decision_log="$job/reviews/reviewer_decisions.attempt-$attempt.log"

  clean_worker_submodules "$job" "$worktree" "$attempt" preflight

  if ! run_worker_preflight "$job" "$status_file" "$id" "$attempt" "$worktree" "$branch" "$base_sha" "$starting_state"; then
    cleanup_current_lock
    return 0
  fi

  # Submodule initialization can leave undeclared submodules dirty when a pinned
  # commit is no longer fetchable. Clean those before prompt generation so the
  # worker sees the same clean worktree the loop will commit and test.
  clean_worker_submodules "$job" "$worktree" "$attempt" preagent

  local prompt_file="$job/worker_prompt.attempt-$attempt.md"
  if [[ ! -s "$task_file" ]]; then
    update_status "$status_file" state=blocked worker_error="task file disappeared or is empty before prompt generation: $task_file"
    cleanup_current_lock
    return 0
  fi
  {
    echo "# Cursor Worker Instructions"
    echo
    echo "You are the Cursor implementation worker for job $id."
    echo
    echo "- Implement only this job."
    echo "- Do not broaden scope or perform unrelated refactors."
    echo "- Do not edit supervisor-owned planning files such as .ai/supervisor/roadmap.md, project_brief.md, ledger.md, or milestone sequencing. If a task appears to require those edits, stop and report that the task must be handled by the Codex supervisor."
    echo "- Work in this Git worktree: $ROOT/$worktree"
    echo "- Base commit SHA for this attempt: $base_sha"
    echo "- Run the requested tests."
    echo "- Break changes into meaningful commits where the task naturally separates into pieces."
    echo "- If files are changed and no meaningful commits exist, leave changes staged or unstaged; the worker loop will create a fallback attempt commit."
    echo "- Finish with a clean structured report using these exact Markdown headings: Summary, Files Changed, Commits Made, Tests Run And Results, Scientific Assumptions, Known Limitations, Suggested Follow-Up, Workflow Friction, Skill Suggestions."
    echo "- Put only final attempt facts in that structured report. Do not copy stale feedback, intermediate reasoning, old attempt claims, or raw tool transcripts into the final structured report."
    echo "- Include a Workflow Friction section. Say 'None' if the job instructions and workflow were clear. Otherwise list missing context, unclear requirements, duplicated/repeated work, painful manual steps, commands that were unavailable, or places where a template/checklist/script would have prevented confusion."
    echo "- Include a Skill Suggestions section. Say 'None' if no new skill is justified."
    echo "- Before proposing a skill, consult existing skills with 'python3 scripts/list_skills.py' when available."
    echo "- Before finalizing, make sure your report and any commit documentation match this attempt's actual commits, tests, and final state. Use the attempt-artifact-consistency skill if available, especially after retry feedback about stale or contradictory attempt artifacts."
    echo "- Do not copy forward stale commit documentation. If you add attempt documentation yourself, it must say exactly which attempt and commit range it covers; the worker loop will also generate the canonical current-attempt commit doc after tests."
    echo "- For each skill suggestion, state proposed name, scope (project-specific or general scientific-coding workflow), when to use it, duplication risk versus existing skills, and the minimal content it should contain."
    echo "- Do not create or edit skills, supervisor protocols, roadmap files, or workflow scripts yourself unless this specific job explicitly assigns that work. Suggestions should be reported for supervisor review."
    echo
    write_available_skills "$ROOT/$worktree"
    echo
    echo "## Task"
    cat "$task_file"
    if [[ -f "$job/feedback.md" ]]; then
      echo
      echo "## Supervisor Feedback"
      cat "$job/feedback.md"
    fi
  } >"$prompt_file"

  local cursor_out="$job/cursor_final.attempt-$attempt.md"
  local cursor_err="$job/cursor_stderr.attempt-$attempt.log"
  local cursor_stream="$job/cursor_stream.attempt-$attempt.jsonl"
  local worker_metrics="$job/metrics.worker.attempt-$attempt.json"
  local worker_exit=0
  local timed_out=false
  local worker_error=""
  local worker_started_at worker_finished_at
  set +e
  worker_started_at="$(utc_now)"
  if [[ "$CURSOR_OUTPUT_FORMAT" == "stream-json" ]]; then
    run_worker_agent "$ROOT/$worktree" "$ROOT/$prompt_file" \
      2> >(tee "$cursor_err" >&2) \
      | tee "$cursor_stream" \
      | python3 "$SCRIPT_DIR/cursor_stream_to_text.py" \
      | tee "$cursor_out"
  else
    run_worker_agent "$ROOT/$worktree" "$ROOT/$prompt_file" 2> >(tee "$cursor_err" >&2) | tee "$cursor_out"
  fi
  worker_exit=${PIPESTATUS[0]}
  worker_finished_at="$(utc_now)"
  set -e
  if [[ "$WORKER_TIMEOUT" != "0" && "$worker_exit" -eq 124 ]]; then
    timed_out=true
    worker_error="worker agent timed out after ${WORKER_TIMEOUT}s"
    echo "$worker_error" | tee -a "$cursor_err" >&2
  elif [[ "$WORKER_TIMEOUT" != "0" && "$worker_exit" -eq 137 ]]; then
    timed_out=true
    worker_error="worker agent was killed after timeout escalation after ${WORKER_TIMEOUT}s"
    echo "$worker_error" | tee -a "$cursor_err" >&2
  elif [[ "$worker_exit" -ne 0 ]]; then
    worker_error="cursor-agent exited with code $worker_exit"
  fi

  local metrics_timeout_arg=()
  if [[ "$timed_out" == true ]]; then
    metrics_timeout_arg=(--timed-out)
  fi
  collect_cursor_metrics \
    --role worker \
    --job-id "$id" \
    --attempt "$attempt" \
    --model "$WORKER_AGENT_WRAPPER:$WORKER_MODEL" \
    --stream "$cursor_stream" \
    --stdout "$cursor_out" \
    --stderr "$cursor_err" \
    --started-at "$worker_started_at" \
    --finished-at "$worker_finished_at" \
    --exit-code "$worker_exit" \
    "${metrics_timeout_arg[@]}" \
    --output "$worker_metrics"

  local pre_commit_head post_cursor_head
  pre_commit_head="$(git -C "$worktree" rev-parse HEAD)"
  post_cursor_head="$pre_commit_head"

  clean_worker_submodules "$job" "$worktree" "$attempt" precommit

  if [[ -n "$(git -C "$worktree" status --porcelain)" ]]; then
    git -C "$worktree" add -A
    git -C "$worktree" commit -m "worker($id): attempt $attempt"
  fi

  post_cursor_head="$(git -C "$worktree" rev-parse HEAD)"

  local test_log="$job/test.attempt-$attempt.log"
  local test_exit=0
  local test_timed_out=false
  if [[ -n "$test_command" ]]; then
    local test_script="$job/test_command.attempt-$attempt.sh"
    mkdir -p "$(dirname "$test_script")"
    cat >"$test_script" <<'TEST_PREAMBLE'
__bbhk_oneapi_setvars="/home/hzhu/intel/oneapi/setvars.sh"
__bbhk_oneapi_loaded=0
__bbhk_sycl_preset="sycl-intel-b580"
__bbhk_sycl_build_dir="build/${__bbhk_sycl_preset}"
__bbhk_icpx_path=""

__bbhk_source_oneapi_for_sycl() {
  if [[ "$__bbhk_oneapi_loaded" == "1" ]]; then
    return 0
  fi
  if [[ ! -f "$__bbhk_oneapi_setvars" ]]; then
    return 0
  fi

  echo "[worker_loop] sourcing oneAPI for sycl-intel-b580: $__bbhk_oneapi_setvars"
  local __bbhk_had_nounset=0
  case "$-" in
    *u*) __bbhk_had_nounset=1 ;;
  esac
  set +u
  # shellcheck disable=SC1090
  local __bbhk_source_status=0
  source "$__bbhk_oneapi_setvars" --force || __bbhk_source_status=$?
  if [[ "$__bbhk_had_nounset" == "1" ]]; then
    set -u
  fi
  if [[ "$__bbhk_source_status" -ne 0 ]]; then
    return "$__bbhk_source_status"
  fi
  __bbhk_oneapi_loaded=1
}

__bbhk_resolve_icpx_for_sycl() {
  __bbhk_source_oneapi_for_sycl || return $?
  if [[ -z "$__bbhk_icpx_path" ]]; then
    __bbhk_icpx_path="$(command -v icpx 2>/dev/null || true)"
    if [[ -z "$__bbhk_icpx_path" ]]; then
      echo "[worker_loop] icpx unavailable after sourcing oneAPI" >&2
      return 127
    fi
  fi
  export CXX="$__bbhk_icpx_path"
}

__bbhk_command_needs_sycl_env() {
  local __bbhk_arg
  for __bbhk_arg in "$@"; do
    if [[ "$__bbhk_arg" == *"$__bbhk_sycl_preset"* || "$__bbhk_arg" == *sycl-ls* ]]; then
      return 0
    fi
  done
  return 1
}

__bbhk_is_sycl_cmake_configure() {
  local __bbhk_seen_build=0
  local __bbhk_seen_preset=0
  local __bbhk_arg
  for __bbhk_arg in "$@"; do
    if [[ "$__bbhk_arg" == "--build" ]]; then
      __bbhk_seen_build=1
    fi
    if [[ "$__bbhk_arg" == "$__bbhk_sycl_preset" ]]; then
      __bbhk_seen_preset=1
    fi
  done
  [[ "$__bbhk_seen_build" == "0" && "$__bbhk_seen_preset" == "1" ]]
}

__bbhk_prepare_sycl_cmake_configure() {
  __bbhk_resolve_icpx_for_sycl || return $?
  if [[ -f "$__bbhk_sycl_build_dir/CMakeCache.txt" ]]; then
    local __bbhk_cached_compiler=""
    __bbhk_cached_compiler="$(
      sed -n 's/^CMAKE_CXX_COMPILER:[^=]*=//p' \
        "$__bbhk_sycl_build_dir/CMakeCache.txt" | head -n 1
    )"
    if [[ "$__bbhk_cached_compiler" != "$__bbhk_icpx_path" ]]; then
      echo "[worker_loop] removing stale $__bbhk_sycl_preset cache with CMAKE_CXX_COMPILER=${__bbhk_cached_compiler:-unset}; expected $__bbhk_icpx_path"
      rm -rf "$__bbhk_sycl_build_dir"
    fi
  fi
}

cmake() {
  if __bbhk_command_needs_sycl_env "$@"; then
    if __bbhk_is_sycl_cmake_configure "$@"; then
      __bbhk_prepare_sycl_cmake_configure || return $?
      command cmake "$@" -DCMAKE_CXX_COMPILER="$__bbhk_icpx_path"
      return $?
    fi
    __bbhk_resolve_icpx_for_sycl || return $?
  fi
  command cmake "$@"
}

ctest() {
  if __bbhk_command_needs_sycl_env "$@"; then
    __bbhk_source_oneapi_for_sycl || return $?
  fi
  command ctest "$@"
}

sycl-ls() {
  __bbhk_source_oneapi_for_sycl || return $?
  command sycl-ls "$@"
}
TEST_PREAMBLE
    {
      printf 'export JOB_ID=%q\n' "$id"
      printf 'export JOB_ATTEMPT=%q\n' "$attempt"
      printf 'export JOB_BRANCH=%q\n' "$branch"
      printf 'export JOB_BASE_SHA=%q\n' "$base_sha"
      printf 'export BASE_SHA=%q\n' "$base_sha"
    } >>"$test_script"
    printf '%s\n' "$test_command" >>"$test_script"
    set +e
    git -C "$worktree" status --short >"$test_log"
    {
      echo
      echo "$ $test_command"
      if [[ "$TEST_TIMEOUT" != "0" ]]; then
        timeout "$TEST_TIMEOUT" bash -c 'cd "$1" && exec bash "$2"' _ \
          "$ROOT/$worktree" "$ROOT/$test_script"
      else
        bash -c 'cd "$1" && exec bash "$2"' _ "$ROOT/$worktree" \
          "$ROOT/$test_script"
      fi
    } >>"$test_log" 2>&1
    test_exit=$?
    rm -f "$test_script"
    set -e
    if grep -q "No tests were found!!!" "$test_log" 2>/dev/null; then
      test_exit=66
      {
        echo
        echo "ERROR: ctest reported that no tests were found. Treating this as a canonical validation failure."
      } >>"$test_log"
    fi
    if [[ "$test_exit" -eq 124 || "$test_exit" -eq 137 ]]; then
      test_timed_out=true
      echo "Test command timed out after ${TEST_TIMEOUT}s" >>"$test_log"
    fi
  else
    echo "No test command specified." >"$test_log"
    test_exit=0
  fi

  local final_commit
  final_commit="$(git -C "$worktree" rev-parse HEAD)"
  local post_test_status="$job/post_test_status.attempt-$attempt.txt"
  local post_test_status_raw="$job/post_test_status_raw.attempt-$attempt.txt"
  # Prefer the worker's branch copy of the allowlist: workers may declare
  # generated artifacts in the job worktree, which the main worktree only
  # sees after integration (J0307 attempt-4 false dirty block, WFI-J0307-5).
  local allowed_artifacts="$job/allowed_artifacts.txt"
  if [[ -f "$worktree/$job/allowed_artifacts.txt" ]]; then
    allowed_artifacts="$worktree/$job/allowed_artifacts.txt"
  fi
  clean_worker_submodules "$job" "$worktree" "$attempt" posttest
  # --untracked-files=all lists new files individually instead of collapsing
  # an untracked directory to one "dir/" entry that per-file allow patterns
  # cannot match (WFI-J0307-5).
  git -C "$worktree" status --porcelain --untracked-files=all >"$post_test_status_raw"
  python3 scripts/filter_allowed_artifacts.py \
    --status "$post_test_status_raw" \
    --allow-file "$allowed_artifacts" \
    --output "$post_test_status" >/dev/null 2>&1 || true
  local post_test_dirty=false
  local post_test_dirty_error=""
  if [[ -s "$post_test_status" ]]; then
    post_test_dirty=true
    post_test_dirty_error="worktree has uncommitted changes after tests; see $post_test_status"
  fi

  git -C "$worktree" diff --name-status "$base_sha..HEAD" >"$job/changed_files.attempt-$attempt.txt" || true
  git -C "$worktree" diff --stat "$base_sha..HEAD" >"$job/diffstat.attempt-$attempt.txt" || true
  git -C "$worktree" diff "$base_sha..HEAD" >"$job/diff.attempt-$attempt.patch" || true

  local handoff_json="$job/worker_handoff.attempt-$attempt.json"
  python3 scripts/extract_worker_handoff.py \
    --job-id "$id" \
    --attempt "$attempt" \
    --raw-output "$cursor_out" \
    --output "$handoff_json" >/dev/null || true

  # Surface handoff quality into status so the supervisor/reviewers can see when
  # the worker's final report was missing/unstructured (a recurring source of
  # stale or contradictory attempt artifacts) instead of it being silent.
  local handoff_quality
  handoff_quality="$(jq -r '.handoff_quality // "unknown"' "$handoff_json" 2>/dev/null || echo unknown)"
  update_status "$status_file" handoff_quality="$handoff_quality"
  if [[ "$handoff_quality" == "missing_or_unstructured" ]]; then
    echo "WARNING: $id attempt $attempt produced a missing/unstructured worker handoff; report fields may be placeholders" \
      | tee -a "$cursor_err" >&2
  fi

  python3 scripts/render_worker_report.py \
    --job-id "$id" \
    --attempt "$attempt" \
    --worker-exit "$worker_exit" \
    --worker-error "$worker_error" \
    --test-command "$test_command" \
    --test-exit "$test_exit" \
    --test-log "$test_log" \
    --final-commit "$final_commit" \
    --base-sha "$base_sha" \
    --changed-files "$job/changed_files.attempt-$attempt.txt" \
    --handoff-json "$handoff_json" \
    --raw-transcript "$cursor_out" \
    --post-test-dirty "$post_test_dirty" \
    --post-test-status "$post_test_status" \
    --output "$job/report.md" >/dev/null

  local tests_passed=false
  if [[ "$test_exit" -eq 0 ]]; then
    tests_passed=true
  fi

  update_status "$status_file" \
    commit="$final_commit" \
    test_exit="$test_exit" \
    test_timed_out="$test_timed_out" \
    tests_passed="$tests_passed" \
    post_test_dirty="$post_test_dirty" \
    post_test_status="$post_test_status" \
    post_test_status_raw="$post_test_status_raw" \
    allowed_artifacts="$allowed_artifacts" \
    changed_files="$job/changed_files.attempt-$attempt.txt" \
    worker_metrics="$worker_metrics" \
    worker_handoff="$handoff_json" \
    report="$job/report.md"

  local commit_doc_path=""
  local commit_doc_log="$job/commit_doc.attempt-$attempt.log"
  commit_doc_path="$(python3 scripts/create_commit_doc.py \
    --job-id "$id" \
    --attempt "$attempt" \
    --branch "$branch" \
    --base-sha "$base_sha" \
    --commit "$final_commit" \
    --test-command "$test_command" \
    --test-exit "$test_exit" \
    --test-log "$test_log" \
    --summary-file "$handoff_json" \
    --handoff-json "$handoff_json" 2>"$commit_doc_log" || true)"
  if [[ -n "$commit_doc_path" ]]; then
    update_status "$status_file" commit_doc="$commit_doc_path"
  else
    # Do not silently discard a commit-doc generation failure: surface it and
    # keep the log. The downstream attempt-consistency check still hard-blocks
    # on the missing canonical commit doc, but the cause is now visible instead
    # of swallowed by 2>/dev/null (see workflow review: silent-failure paths).
    echo "WARNING: commit doc generation failed for $id attempt $attempt; see $commit_doc_log" \
      | tee -a "$cursor_err" >&2
  fi

  local consistency_exit=0
  run_attempt_consistency_check "$job" "$status_file" "$attempt" "$worktree" "$base_sha" "$final_commit" "$test_log" "$job/report.md" "$handoff_json" || consistency_exit=$?

  local cursor_reported_success=false
  if grep -q '\[system success\]' "$cursor_out" 2>/dev/null; then
    cursor_reported_success=true
  fi

  local next_state=ready_for_review
  local hard_block=false
  local worker_soft_success=false
  if [[ "$worker_exit" -ne 0 && "$cursor_reported_success" == true && "$tests_passed" == true && "$post_test_dirty" != true ]]; then
    worker_soft_success=true
    worker_error="${worker_error:+$worker_error; }cursor-agent returned nonzero after reporting system success; continuing to reviewer stage"
    echo "$worker_error" | tee -a "$cursor_err" >&2
  elif [[ "$worker_exit" -ne 0 ]]; then
    next_state=blocked
  fi
  if [[ "$post_test_dirty" == true ]]; then
    next_state=blocked
    hard_block=true
    worker_error="${worker_error:+$worker_error; }$post_test_dirty_error"
  fi
  if [[ "$tests_passed" != true ]]; then
    next_state=blocked
    hard_block=true
    worker_error="${worker_error:+$worker_error; }test command failed with exit $test_exit; see $test_log"
  fi
  if [[ "$consistency_exit" -ne 0 ]]; then
    next_state=blocked
    hard_block=true
    worker_error="${worker_error:+$worker_error; }attempt consistency check failed; see $job/attempt_consistency.attempt-$attempt.md"
  fi
  if [[ "$next_state" == "blocked" && "$worker_soft_success" != true && "$worker_exit" -ne 0 && "$timed_out" != true && "$hard_block" != true && "$WORKER_AUTO_RELAUNCH_FAILURE" == "1" && "$attempt" -lt "$WORKER_MAX_FAILURE_RESUMES" ]]; then
    next_state=queued
    echo "Requeueing $id after worker failure attempt $attempt; max failure resumes: $WORKER_MAX_FAILURE_RESUMES"
  fi
  if [[ "$timed_out" == true && "$hard_block" != true && "$WORKER_AUTO_RESUME_TIMEOUT" == "1" && "$attempt" -lt "$WORKER_MAX_TIMEOUT_RESUMES" ]]; then
    next_state=queued
    echo "Requeueing $id after timeout attempt $attempt; max timeout resumes: $WORKER_MAX_TIMEOUT_RESUMES"
  fi

  if ! attempt_still_active "$status_file" "$id" "$attempt" "worker finalization" running; then
    cleanup_current_lock
    return 0
  fi

  if [[ "$next_state" == "ready_for_review" ]]; then
    local reviewer_status=0
    run_reviewers "$job" "$status_file" "$id" "$attempt" "$worktree" "$base_sha" "$final_commit" || reviewer_status=$?
    if [[ "$reviewer_status" -eq 124 ]]; then
      next_state=review_timeout
    elif [[ "$reviewer_status" -eq 125 ]]; then
      cleanup_current_lock
      return 0
    elif [[ "$reviewer_status" -ne 0 ]]; then
      next_state=review_failed
    fi
  fi

  if ! attempt_still_active "$status_file" "$id" "$attempt" "status finalization" running reviewing; then
    cleanup_current_lock
    return 0
  fi

  if [[ "$next_state" == "blocked" ]]; then
    record_event \
      --kind failure \
      --role worker \
      --reason-code worker_blocked \
      --reason "${worker_error:-worker job blocked}" \
      --job-id "$id" \
      --attempt "$attempt" \
      --state "$next_state" \
      --path "$job/report.md"
  elif [[ "$next_state" == "review_failed" || "$next_state" == "review_timeout" ]]; then
    record_event \
      --kind failure \
      --role reviewer \
      --reason-code "$next_state" \
      --reason "reviewer stage did not complete cleanly" \
      --job-id "$id" \
      --attempt "$attempt" \
      --state "$next_state" \
      --path "$job/reviews"
  fi

  update_status "$status_file" \
    state="$next_state" \
    attempt="$attempt" \
    base_sha="$base_sha" \
    workflow_commit="$workflow_commit" \
    worker_exit="$worker_exit" \
    cursor_reported_success="$cursor_reported_success" \
    timed_out="$timed_out" \
    worker_error="$worker_error" \
    auto_resume_timeout="$WORKER_AUTO_RESUME_TIMEOUT" \
    test_exit="$test_exit" \
    test_timed_out="$test_timed_out" \
    tests_passed="$tests_passed" \
    post_test_dirty="$post_test_dirty" \
    post_test_status="$post_test_status" \
    post_test_status_raw="$post_test_status_raw" \
    allowed_artifacts="$allowed_artifacts" \
    attempt_consistency_exit="$consistency_exit" \
    attempt_consistency_log="$job/attempt_consistency.attempt-$attempt.md" \
    changed_files="$job/changed_files.attempt-$attempt.txt" \
    worker_metrics="$worker_metrics" \
    commit="$final_commit" \
    commit_doc="$(canonical_commit_doc_path "$id" "$attempt" "$final_commit")" \
    report="$job/report.md"

  cleanup_current_lock
}

review_existing_job() {
  local job="$1"
  local status_file="$job/status.json"
  local lock_dir="$job/.lock"

  if ! mkdir "$lock_dir" 2>/dev/null; then
    return 0
  fi
  CURRENT_LOCK="$lock_dir"
  mark_current_lock_owned

  local id branch attempt worktree base_sha final_commit reviewer_status next_state
  id="$(json_field "$status_file" id)"
  branch="$(json_field "$status_file" branch)"
  attempt="$(jq -r '.attempt // 0' "$status_file")"
  base_sha="$(json_field "$status_file" base_sha)"
  final_commit="$(json_field "$status_file" commit)"
  worktree=".worktrees/$id"

  if [[ -z "$id" || -z "$branch" || -z "$base_sha" || -z "$final_commit" || "$attempt" == "0" ]]; then
    update_status "$status_file" state=blocked worker_error="implemented job is missing id, branch, base_sha, commit, or attempt"
    cleanup_current_lock
    return 0
  fi
  if ! git -C "$worktree" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    update_status "$status_file" state=blocked worker_error="implemented job worktree is missing or invalid: $worktree"
    cleanup_current_lock
    return 0
  fi
  if ! git -C "$worktree" merge-base --is-ancestor "$base_sha" "$final_commit" >/dev/null 2>&1; then
    update_status "$status_file" state=blocked worker_error="implemented job commit is not reachable from base_sha: $base_sha..$final_commit"
    cleanup_current_lock
    return 0
  fi
  if ! run_progress_gate "$job" "$status_file" "$job/task.md" "$attempt"; then
    cleanup_current_lock
    return 0
  fi
  if [[ "$(jq -r '.tests_passed // false' "$status_file")" != "true" ]]; then
    update_status "$status_file" \
      state=blocked \
      workflow_commit="$workflow_commit" \
      worker_error="implemented job has failing canonical tests; rerun or reject before review" \
      report="$job/report.md"
    cleanup_current_lock
    return 0
  fi

  if [[ ! -s "$job/changed_files.attempt-$attempt.txt" ]]; then
    git -C "$worktree" diff --name-status "$base_sha..$final_commit" >"$job/changed_files.attempt-$attempt.txt" || true
  fi
  if [[ ! -s "$job/diffstat.attempt-$attempt.txt" ]]; then
    git -C "$worktree" diff --stat "$base_sha..$final_commit" >"$job/diffstat.attempt-$attempt.txt" || true
  fi
  if [[ ! -s "$job/diff.attempt-$attempt.patch" ]]; then
    git -C "$worktree" diff "$base_sha..$final_commit" >"$job/diff.attempt-$attempt.patch" || true
  fi

  local existing_consistency_exit=0
  local existing_handoff_json="$job/worker_handoff.attempt-$attempt.json"
  run_attempt_consistency_check "$job" "$status_file" "$attempt" "$worktree" "$base_sha" "$final_commit" "$job/test.attempt-$attempt.log" "$job/report.md" "$existing_handoff_json" || existing_consistency_exit=$?
  if [[ "$existing_consistency_exit" -ne 0 ]]; then
    update_status "$status_file" \
      state=blocked \
      workflow_commit="$workflow_commit" \
      worker_error="attempt consistency check failed; see $job/attempt_consistency.attempt-$attempt.md" \
      report="$job/report.md"
    cleanup_current_lock
    return 0
  fi

  reviewer_status=0
  run_reviewers "$job" "$status_file" "$id" "$attempt" "$worktree" "$base_sha" "$final_commit" || reviewer_status=$?
  if [[ "$reviewer_status" -eq 125 ]]; then
    cleanup_current_lock
    return 0
  fi
  next_state=ready_for_review
  if [[ "$reviewer_status" -eq 124 ]]; then
    next_state=review_timeout
  elif [[ "$reviewer_status" -ne 0 ]]; then
    next_state=review_failed
  fi

  if ! attempt_still_active "$status_file" "$id" "$attempt" "implemented review finalization" implemented reviewing; then
    cleanup_current_lock
    return 0
  fi

  update_status "$status_file" \
    state="$next_state" \
    workflow_commit="$workflow_commit" \
    report="$job/report.md"

  cleanup_current_lock
}

dispatch_pids=()

# Block until fewer than WORKER_MAX_PARALLEL_JOBS background dispatches remain.
# Portable (no `wait -n`, which is unavailable on macOS bash 3.2): wait for the
# oldest dispatched PID first (FIFO).
throttle_dispatch() {
  while (( ${#dispatch_pids[@]} >= WORKER_MAX_PARALLEL_JOBS )); do
    wait "${dispatch_pids[0]}" 2>/dev/null || true
    dispatch_pids=("${dispatch_pids[@]:1}")
  done
}

auto_integrate_ready_jobs() {
  [[ "$WORKER_AUTO_INTEGRATE" == "1" ]] || return 0
  shopt -s nullglob
  for status_file in .ai/jobs/J*/status.json; do
    local state job id
    state="$(jq -r '.state // ""' "$status_file")"
    [[ "$state" == "ready_for_review" ]] || continue
    job="$(dirname "$status_file")"
    id="$(basename "$job")"
    # integrate_job.py --apply re-verifies every gate (state, reviewers_complete,
    # reviewer blocks, attempt consistency, clean main worktree) and is a no-op
    # if any fails, so a gate-failing job is safely skipped here.
    echo "Auto-integrating $id ($WORKER_AUTO_INTEGRATE_METHOD)"
    if python3 scripts/integrate_job.py "$id" --apply --method "$WORKER_AUTO_INTEGRATE_METHOD"; then
      local integration_commit
      integration_commit="$(git rev-parse HEAD 2>/dev/null || echo "")"
      # Mark accepted so the job is not re-merged on the next scan, recording the
      # integration commit; then prune its worktree/branch.
      python3 scripts/transition_job.py "$status_file" accepted \
        "integration_commit=$integration_commit" 2>/dev/null \
        || echo "WARNING: integrated $id but failed to mark accepted; will need manual state fix"
      python3 scripts/prune_accepted_job_refs.py --job "$id" 2>/dev/null || true
    else
      echo "Auto-integration skipped for $id (gates not satisfied or merge blocked)"
    fi
  done
  shopt -u nullglob
}

while true; do
  if [[ -f "$HUMAN_GATE" || -f "$STRUCTURAL_REQUEST" || -f "$HUMAN_REVIEW_ACTION_REQUEST" || -f "$SUPERVISOR_ACTION_REQUEST" ]]; then
    sleep "$POLL_SECONDS"
    continue
  fi

  recover_stale_running_jobs

  found=0
  shopt -s nullglob
  for status_file in .ai/jobs/J*/status.json; do
    state="$(jq -r '.state // ""' "$status_file")"
    job_dir="$(dirname "$status_file")"
    action=""
    if [[ "$state" == "queued" || "$state" == "rejected" ]]; then
      action=process_job
    elif [[ "$state" == "implemented" ]]; then
      action=review_existing_job
    else
      continue
    fi
    found=1
    if [[ "$WORKER_MAX_PARALLEL_JOBS" -le 1 ]]; then
      "$action" "$job_dir"
    else
      throttle_dispatch
      "$action" "$job_dir" &
      dispatch_pids+=("$!")
    fi
  done
  shopt -u nullglob

  # Drain the parallel batch fully before rescanning so no job is dispatched
  # twice (a still-queued job would otherwise be re-picked next scan).
  if [[ "${#dispatch_pids[@]}" -gt 0 ]]; then
    wait "${dispatch_pids[@]}" 2>/dev/null || true
    dispatch_pids=()
  fi

  auto_integrate_ready_jobs

  if [[ "$found" -eq 0 ]]; then
    sleep "$POLL_SECONDS"
  fi
done
