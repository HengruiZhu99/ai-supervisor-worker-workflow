#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOW_PACKAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export AI_WORKFLOW_PACKAGE_ROOT="${AI_WORKFLOW_PACKAGE_ROOT:-$WORKFLOW_PACKAGE_ROOT}"
cd "$ROOT"

CURSOR_TIMEOUT="${CURSOR_TIMEOUT:-3600}"
WORKER_AGENT_WRAPPER="${WORKER_AGENT_WRAPPER:-${CURSOR_AGENT_WRAPPER:-cursor-agent}}"
WORKER_MODEL="${WORKER_MODEL:-${CURSOR_MODEL:-gpt-5.5-high}}"
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
WORKER_AUTO_RESUME_TIMEOUT="${WORKER_AUTO_RESUME_TIMEOUT:-0}"
WORKER_MAX_TIMEOUT_RESUMES="${WORKER_MAX_TIMEOUT_RESUMES:-1}"
WORKER_AUTO_RELAUNCH_FAILURE="${WORKER_AUTO_RELAUNCH_FAILURE:-1}"
WORKER_MAX_FAILURE_RESUMES="${WORKER_MAX_FAILURE_RESUMES:-2}"
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
    *)
      echo "$1"
      ;;
  esac
}

WORKER_MODEL="$(normalize_cursor_model "$WORKER_MODEL")"
REVIEWER_A_MODEL="$(normalize_cursor_model "$REVIEWER_A_MODEL")"
REVIEWER_B_MODEL="$(normalize_cursor_model "$REVIEWER_B_MODEL")"

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
    rm -f "$LOOP_LOCK/pid" "$LOOP_LOCK/started_at" 2>/dev/null || true
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
echo "workflow_commit=$workflow_commit"
echo "worker_agent_wrapper=$WORKER_AGENT_WRAPPER"
echo "worker_model=$WORKER_MODEL"
echo "reviewer_a_agent_wrapper=$REVIEWER_A_AGENT_WRAPPER"
echo "reviewer_a_model=$REVIEWER_A_MODEL"
echo "reviewer_b_agent_wrapper=$REVIEWER_B_AGENT_WRAPPER"
echo "reviewer_b_model=$REVIEWER_B_MODEL"

write_available_skills() {
  echo "## Available Skills"
  echo
  echo "These project and workflow skills are visible in this worktree. When a skill is relevant, read the listed SKILL.md file before applying it."
  echo
  echo '```text'
  if ! python3 "$AI_WORKFLOW_PACKAGE_ROOT/scripts/list_skills.py" 2>/dev/null; then
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
  timeout "$CURSOR_TIMEOUT" \
    python3 scripts/agent_wrapper.py run \
      --role worker \
      --wrapper "$WORKER_AGENT_WRAPPER" \
      --model "$WORKER_MODEL" \
      --workspace "$worktree" \
      --prompt-file "$prompt_file" \
      --output-format "$CURSOR_OUTPUT_FORMAT" \
      "${stream_args[@]}" \
      --extra-args="$WORKER_AGENT_EXTRA_ARGS"
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
    return 0
  fi
  echo "failed to acquire worker loop lock: $lock_dir" >&2
  exit 1
}

clear_known_stale_lock() {
  local lock_dir="$1"
  rm -f "$lock_dir/pid" "$lock_dir/started_at" 2>/dev/null || true
  rmdir "$lock_dir" 2>/dev/null
}

record_event() {
  python3 scripts/record_workflow_event.py "$@" >/dev/null 2>&1 || true
}

acquire_loop_lock

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
  local focus

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
    echo "- Commit docs: $ROOT/.ai/commit_docs/"
    echo "- Existing skills: run 'python3 scripts/list_skills.py' in the worktree if needed. The environment variable AI_WORKFLOW_PACKAGE_ROOT is set to $AI_WORKFLOW_PACKAGE_ROOT."
    echo
    write_available_skills
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

  if [[ "$CURSOR_REVIEWERS_ENABLED" != "1" ]]; then
    update_status "$status_file" reviewers_enabled=false
    return 0
  fi

  update_status "$status_file" \
    state=reviewing \
    reviewers_enabled=true \
    reviewers_parallel=true \
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

  update_status "$status_file" \
    reviewer_a_exit="$reviewer_a_exit" \
    reviewer_b_exit="$reviewer_b_exit" \
    reviewer_coverage_exit="$coverage_exit" \
    reviewer_decision_exit="$decision_exit" \
    reviewers_complete="$([[ "$reviewer_a_exit" -eq 0 && "$reviewer_b_exit" -eq 0 && "$coverage_exit" -eq 0 && "$decision_exit" -eq 0 ]] && echo true || echo false)" \
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
  attempt="$(jq -r '(.attempt // 0) + 1' "$status_file")"
  starting_state="$(jq -r '.state // ""' "$status_file")"
  worktree=".worktrees/$id"
  local task_file="$job/task.md"

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

  update_status "$status_file" state=running attempt="$attempt" branch="$branch" base_sha="$base_sha" workflow_commit="$workflow_commit"

  if ! run_worker_preflight "$job" "$status_file" "$id" "$attempt" "$worktree" "$branch" "$base_sha" "$starting_state"; then
    cleanup_current_lock
    return 0
  fi

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
    echo "- For each skill suggestion, state proposed name, scope (project-specific or general scientific-coding workflow), when to use it, duplication risk versus existing skills, and the minimal content it should contain."
    echo "- Do not create or edit skills, supervisor protocols, roadmap files, or workflow scripts yourself unless this specific job explicitly assigns that work. Suggestions should be reported for supervisor review."
    echo
    write_available_skills
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
  if [[ "$worker_exit" -eq 124 ]]; then
    timed_out=true
    worker_error="cursor-agent timed out after ${CURSOR_TIMEOUT}s"
    echo "$worker_error" | tee -a "$cursor_err" >&2
  elif [[ "$worker_exit" -eq 137 ]]; then
    timed_out=true
    worker_error="cursor-agent was killed after timeout escalation after ${CURSOR_TIMEOUT}s"
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
    set +e
    git -C "$worktree" status --short >"$test_log"
    {
      echo
      echo "$ $test_command"
      if [[ "$TEST_TIMEOUT" != "0" ]]; then
        timeout "$TEST_TIMEOUT" bash -lc "cd '$ROOT/$worktree' && $test_command"
      else
        bash -lc "cd '$ROOT/$worktree' && $test_command"
      fi
    } >>"$test_log" 2>&1
    test_exit=$?
    set -e
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
  local allowed_artifacts="$job/allowed_artifacts.txt"
  clean_worker_submodules "$job" "$worktree" "$attempt" posttest
  git -C "$worktree" status --porcelain >"$post_test_status_raw"
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
    worker_handoff="$handoff_json" \
    report="$job/report.md"

  python3 scripts/create_commit_doc.py \
    --job-id "$id" \
    --attempt "$attempt" \
    --branch "$branch" \
    --base-sha "$base_sha" \
    --commit "$final_commit" \
    --test-command "$test_command" \
    --test-exit "$test_exit" \
    --test-log "$test_log" \
    --summary-file "$handoff_json" \
    --handoff-json "$handoff_json" >/dev/null || true

  local consistency_exit=0
  run_attempt_consistency_check "$job" "$status_file" "$attempt" "$worktree" "$base_sha" "$final_commit" "$test_log" "$job/report.md" "$handoff_json" || consistency_exit=$?

  local cursor_reported_success=false
  if grep -q '\[system success\]' "$cursor_out" 2>/dev/null; then
    cursor_reported_success=true
  fi

  local next_state=ready_for_review
  local hard_block=false
  if [[ "$worker_exit" -ne 0 && "$cursor_reported_success" == true && "$tests_passed" == true && "$post_test_dirty" != true ]]; then
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
  if [[ "$consistency_exit" -ne 0 ]]; then
    next_state=blocked
    hard_block=true
    worker_error="${worker_error:+$worker_error; }attempt consistency check failed; see $job/attempt_consistency.attempt-$attempt.md"
  fi
  if [[ "$worker_exit" -ne 0 && "$timed_out" != true && "$hard_block" != true && "$WORKER_AUTO_RELAUNCH_FAILURE" == "1" && "$attempt" -lt "$WORKER_MAX_FAILURE_RESUMES" ]]; then
    next_state=queued
    echo "Requeueing $id after worker failure attempt $attempt; max failure resumes: $WORKER_MAX_FAILURE_RESUMES"
  fi
  if [[ "$timed_out" == true && "$hard_block" != true && "$WORKER_AUTO_RESUME_TIMEOUT" == "1" && "$attempt" -lt "$WORKER_MAX_TIMEOUT_RESUMES" ]]; then
    next_state=queued
    echo "Requeueing $id after timeout attempt $attempt; max timeout resumes: $WORKER_MAX_TIMEOUT_RESUMES"
  fi

  if [[ "$next_state" == "ready_for_review" ]]; then
    local reviewer_status=0
    run_reviewers "$job" "$status_file" "$id" "$attempt" "$worktree" "$base_sha" "$final_commit" || reviewer_status=$?
    if [[ "$reviewer_status" -eq 124 ]]; then
      next_state=review_timeout
    elif [[ "$reviewer_status" -ne 0 ]]; then
      next_state=review_failed
    fi
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
  next_state=ready_for_review
  if [[ "$reviewer_status" -eq 124 ]]; then
    next_state=review_timeout
  elif [[ "$reviewer_status" -ne 0 ]]; then
    next_state=review_failed
  fi

  update_status "$status_file" \
    state="$next_state" \
    workflow_commit="$workflow_commit" \
    report="$job/report.md"

  cleanup_current_lock
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
    if [[ "$state" == "queued" || "$state" == "rejected" ]]; then
      found=1
      process_job "$(dirname "$status_file")"
    elif [[ "$state" == "implemented" ]]; then
      found=1
      review_existing_job "$(dirname "$status_file")"
    fi
  done
  shopt -u nullglob

  if [[ "$found" -eq 0 ]]; then
    sleep "$POLL_SECONDS"
  fi
done
