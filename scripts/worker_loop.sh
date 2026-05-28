#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

CURSOR_TIMEOUT="${CURSOR_TIMEOUT:-3600}"
CURSOR_MODEL="${CURSOR_MODEL:-gpt-5.5-high}"
CURSOR_AGENT_EXTRA_ARGS="${CURSOR_AGENT_EXTRA_ARGS:-}"
CURSOR_OUTPUT_FORMAT="${CURSOR_OUTPUT_FORMAT:-stream-json}"
CURSOR_STREAM_PARTIAL_OUTPUT="${CURSOR_STREAM_PARTIAL_OUTPUT:-1}"
CURSOR_REVIEWERS_ENABLED="${CURSOR_REVIEWERS_ENABLED:-1}"
CURSOR_REVIEW_TIMEOUT="${CURSOR_REVIEW_TIMEOUT:-2400}"
CURSOR_REVIEWER_A_MODEL="${CURSOR_REVIEWER_A_MODEL:-claude-opus-4-7-thinking-high}"
CURSOR_REVIEWER_B_MODEL="${CURSOR_REVIEWER_B_MODEL:-gpt-5.3-codex-high}"
CURSOR_REVIEWER_EXTRA_ARGS="${CURSOR_REVIEWER_EXTRA_ARGS:-}"
WORKER_AUTO_RESUME_TIMEOUT="${WORKER_AUTO_RESUME_TIMEOUT:-0}"
WORKER_MAX_TIMEOUT_RESUMES="${WORKER_MAX_TIMEOUT_RESUMES:-1}"
POLL_SECONDS="${POLL_SECONDS:-5}"
CURRENT_LOCK=""

cleanup_current_lock() {
  if [[ -n "${CURRENT_LOCK:-}" ]]; then
    rmdir "$CURRENT_LOCK" 2>/dev/null || true
    CURRENT_LOCK=""
  fi
}

stop_worker_loop() {
  cleanup_current_lock
  exit 143
}

interrupt_worker_loop() {
  cleanup_current_lock
  exit 130
}

trap cleanup_current_lock EXIT
trap interrupt_worker_loop INT
trap stop_worker_loop TERM

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing required command: $1" >&2
    exit 1
  }
}

for cmd in git jq python3 timeout cursor-agent; do
  require_command "$cmd"
done

run_cursor_agent() {
  local worktree="$1"
  local prompt_file="$2"

  # Edit only this function if `cursor-agent --help` shows different flags.
  # The workflow protocol around this invocation is intentionally filesystem-based.
  # Set CURSOR_MODEL to choose a model, for example:
  #   CURSOR_MODEL=gpt-5.5-high ./scripts/worker_loop.sh
  # The default stream-json mode lets the dashboard show partial model output.
  # Set CURSOR_OUTPUT_FORMAT=text to restore Cursor's plain final-output mode.
  # Set CURSOR_AGENT_EXTRA_ARGS for local flags such as --force if desired.
  local output_args=(--output-format "$CURSOR_OUTPUT_FORMAT")
  if [[ "$CURSOR_OUTPUT_FORMAT" == "stream-json" && "$CURSOR_STREAM_PARTIAL_OUTPUT" == "1" ]]; then
    output_args+=(--stream-partial-output)
  fi
  # shellcheck disable=SC2086
  timeout "$CURSOR_TIMEOUT" \
    cursor-agent -p --trust --workspace "$worktree" "${output_args[@]}" --model "$CURSOR_MODEL" $CURSOR_AGENT_EXTRA_ARGS "$(cat "$prompt_file")"
}

run_cursor_reviewer() {
  local worktree="$1"
  local prompt_file="$2"
  local model="$3"

  local output_args=(--output-format "$CURSOR_OUTPUT_FORMAT")
  if [[ "$CURSOR_OUTPUT_FORMAT" == "stream-json" && "$CURSOR_STREAM_PARTIAL_OUTPUT" == "1" ]]; then
    output_args+=(--stream-partial-output)
  fi
  # Reviewers run in Cursor ask mode so their role is critique only. If your
  # local cursor-agent changes read-only mode flags, edit only this function.
  # shellcheck disable=SC2086
  timeout "$CURSOR_REVIEW_TIMEOUT" \
    cursor-agent -p --trust --mode ask --workspace "$worktree" "${output_args[@]}" --model "$model" $CURSOR_REVIEWER_EXTRA_ARGS "$(cat "$prompt_file")"
}

update_status() {
  local status_file="$1"
  shift
  python3 scripts/update_job_status.py "$status_file" "$@" >/dev/null
}

json_field() {
  local status_file="$1"
  local field="$2"
  jq -r --arg field "$field" '.[$field] // ""' "$status_file"
}

write_reviewer_prompt() {
  local role="$1"
  local job="$2"
  local id="$3"
  local attempt="$4"
  local worktree="$5"
  local base_ref="$6"
  local final_commit="$7"
  local prompt_file="$8"
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
    echo "- Base ref: $base_ref"
    echo "- Final worker commit: $final_commit"
    echo "- Task: $ROOT/$job/task.md"
    echo "- Worker report: $ROOT/$job/report.md"
    echo "- Diffstat: $ROOT/$job/diffstat.attempt-$attempt.txt"
    echo "- Patch: $ROOT/$job/diff.attempt-$attempt.patch"
    echo "- Test log: $ROOT/$job/test.attempt-$attempt.log"
    echo "- Commit docs: $ROOT/.ai/commit_docs/"
    echo "- Existing skills: run 'python3 scripts/list_skills.py' in the worktree if needed"
    echo
    echo "Read the task, worker report, test log, diffstat, and selected patch/source sections. Check whether the worker stayed in scope and whether the evidence supports acceptance."
    echo
    echo "## Output Format"
    echo
    echo "Return a concise markdown report with:"
    echo "1. Recommendation: accept, revise, or needs-supervisor-judgment"
    echo "2. Blocking concerns"
    echo "3. Nonblocking concerns"
    echo "4. Evidence reviewed"
    echo "5. Test and validation assessment"
    echo "6. Scope assessment"
    echo "7. Suggested supervisor decision rationale"
    echo "8. Skill suggestion review: whether the worker's suggested skills are useful, duplicate existing skills, and should be project-specific, general workflow skills, deferred, or rejected. Run 'python3 scripts/list_skills.py' if needed."
  } >"$prompt_file"
}

run_one_reviewer() {
  local role="$1"
  local model="$2"
  local job="$3"
  local id="$4"
  local attempt="$5"
  local worktree="$6"
  local base_ref="$7"
  local final_commit="$8"
  local reviews_dir="$job/reviews"

  mkdir -p "$reviews_dir"

  local prompt_file="$reviews_dir/$role.prompt.attempt-$attempt.md"
  local review_out="$reviews_dir/$role.attempt-$attempt.md"
  local review_err="$reviews_dir/$role.stderr.attempt-$attempt.log"
  local review_stream="$reviews_dir/$role.stream.attempt-$attempt.jsonl"
  local reviewer_exit=0

  write_reviewer_prompt "$role" "$job" "$id" "$attempt" "$worktree" "$base_ref" "$final_commit" "$prompt_file"

  set +e
  if [[ "$CURSOR_OUTPUT_FORMAT" == "stream-json" ]]; then
    run_cursor_reviewer "$ROOT/$worktree" "$ROOT/$prompt_file" "$model" \
      2> >(tee "$review_err" >&2) \
      | tee "$review_stream" \
      | python3 "$SCRIPT_DIR/cursor_stream_to_text.py" \
      | tee "$review_out"
  else
    run_cursor_reviewer "$ROOT/$worktree" "$ROOT/$prompt_file" "$model" 2> >(tee "$review_err" >&2) | tee "$review_out"
  fi
  reviewer_exit=${PIPESTATUS[0]}
  set -e

  if [[ "$reviewer_exit" -eq 124 ]]; then
    echo "Reviewer $role timed out after ${CURSOR_REVIEW_TIMEOUT}s" | tee -a "$review_err" >&2
  elif [[ "$reviewer_exit" -ne 0 ]]; then
    echo "Reviewer $role exited with code $reviewer_exit" | tee -a "$review_err" >&2
  fi

  return "$reviewer_exit"
}

run_reviewers() {
  local job="$1"
  local status_file="$2"
  local id="$3"
  local attempt="$4"
  local worktree="$5"
  local base_ref="$6"
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
    reviewer_a_model="$CURSOR_REVIEWER_A_MODEL" \
    reviewer_b_model="$CURSOR_REVIEWER_B_MODEL"

  run_one_reviewer "reviewer-a" "$CURSOR_REVIEWER_A_MODEL" "$job" "$id" "$attempt" "$worktree" "$base_ref" "$final_commit" || reviewer_a_exit=$?
  run_one_reviewer "reviewer-b" "$CURSOR_REVIEWER_B_MODEL" "$job" "$id" "$attempt" "$worktree" "$base_ref" "$final_commit" || reviewer_b_exit=$?

  update_status "$status_file" \
    reviewer_a_exit="$reviewer_a_exit" \
    reviewer_b_exit="$reviewer_b_exit" \
    reviewer_a_report="$job/reviews/reviewer-a.attempt-$attempt.md" \
    reviewer_b_report="$job/reviews/reviewer-b.attempt-$attempt.md"

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

  local id base_ref branch test_command attempt worktree current_branch
  id="$(json_field "$status_file" id)"
  base_ref="$(json_field "$status_file" base_ref)"
  branch="$(json_field "$status_file" branch)"
  test_command="$(json_field "$status_file" test_command)"
  attempt="$(jq -r '(.attempt // 0) + 1' "$status_file")"
  worktree=".worktrees/$id"

  if [[ -z "$id" || -z "$base_ref" || -z "$branch" ]]; then
    update_status "$status_file" state=blocked worker_error="missing id, base_ref, or branch"
    cleanup_current_lock
    return 0
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
      git worktree add "$worktree" "$branch"
    else
      git worktree add -b "$branch" "$worktree" "$base_ref"
    fi
  fi

  update_status "$status_file" state=running attempt="$attempt" branch="$branch"

  local prompt_file="$job/worker_prompt.attempt-$attempt.md"
  {
    echo "# Cursor Worker Instructions"
    echo
    echo "You are the Cursor implementation worker for job $id."
    echo
    echo "- Implement only this job."
    echo "- Do not broaden scope or perform unrelated refactors."
    echo "- Work in this Git worktree: $ROOT/$worktree"
    echo "- Run the requested tests."
    echo "- Break changes into meaningful commits where the task naturally separates into pieces."
    echo "- If files are changed and no meaningful commits exist, leave changes staged or unstaged; the worker loop will create a fallback attempt commit."
    echo "- Return a concise report with summary, files changed, commits made, tests run and results, scientific assumptions, known limitations, and suggested follow-up."
    echo "- Include a Skill Suggestions section. Say 'None' if no new skill is justified."
    echo "- Before proposing a skill, consult existing skills with 'python3 scripts/list_skills.py' when available."
    echo "- For each skill suggestion, state proposed name, scope (project-specific or general scientific-coding workflow), when to use it, duplication risk versus existing skills, and the minimal content it should contain."
    echo
    echo "## Task"
    cat "$job/task.md"
    if [[ -f "$job/feedback.md" ]]; then
      echo
      echo "## Supervisor Feedback"
      cat "$job/feedback.md"
    fi
  } >"$prompt_file"

  local cursor_out="$job/cursor_final.attempt-$attempt.md"
  local cursor_err="$job/cursor_stderr.attempt-$attempt.log"
  local cursor_stream="$job/cursor_stream.attempt-$attempt.jsonl"
  local worker_exit=0
  local timed_out=false
  local worker_error=""
  set +e
  if [[ "$CURSOR_OUTPUT_FORMAT" == "stream-json" ]]; then
    run_cursor_agent "$ROOT/$worktree" "$ROOT/$prompt_file" \
      2> >(tee "$cursor_err" >&2) \
      | tee "$cursor_stream" \
      | python3 "$SCRIPT_DIR/cursor_stream_to_text.py" \
      | tee "$cursor_out"
  else
    run_cursor_agent "$ROOT/$worktree" "$ROOT/$prompt_file" 2> >(tee "$cursor_err" >&2) | tee "$cursor_out"
  fi
  worker_exit=${PIPESTATUS[0]}
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

  local pre_commit_head post_cursor_head
  pre_commit_head="$(git -C "$worktree" rev-parse HEAD)"
  post_cursor_head="$pre_commit_head"

  if [[ -n "$(git -C "$worktree" status --porcelain)" ]]; then
    git -C "$worktree" add -A
    git -C "$worktree" commit -m "worker($id): attempt $attempt"
  fi

  post_cursor_head="$(git -C "$worktree" rev-parse HEAD)"

  local test_log="$job/test.attempt-$attempt.log"
  local test_exit=0
  if [[ -n "$test_command" ]]; then
    set +e
    git -C "$worktree" status --short >"$test_log"
    {
      echo
      echo "$ $test_command"
      bash -lc "cd '$ROOT/$worktree' && $test_command"
    } >>"$test_log" 2>&1
    test_exit=$?
    set -e
  else
    echo "No test command specified." >"$test_log"
    test_exit=0
  fi

  local final_commit
  final_commit="$(git -C "$worktree" rev-parse HEAD)"

  git -C "$worktree" diff --stat "$base_ref..HEAD" >"$job/diffstat.attempt-$attempt.txt" || true
  git -C "$worktree" diff "$base_ref..HEAD" >"$job/diff.attempt-$attempt.patch" || true

  {
    echo "# Worker Report: $id Attempt $attempt"
    echo
    echo "## Summary"
    cat "$cursor_out"
    echo
    echo "## Worker exit"
    echo "$worker_exit"
    if [[ -n "$worker_error" ]]; then
      echo
      echo "## Worker error"
      echo "$worker_error"
    fi
    echo
    echo "## Test exit"
    echo "$test_exit"
    echo
    echo "## Final commit"
    echo "$final_commit"
  } >"$job/report.md"

  python3 scripts/create_commit_doc.py \
    --job-id "$id" \
    --attempt "$attempt" \
    --branch "$branch" \
    --commit "$final_commit" \
    --test-command "$test_command" \
    --test-exit "$test_exit" \
    --test-log "$test_log" \
    --summary-file "$cursor_out" >/dev/null || true

  local tests_passed=false
  if [[ "$test_exit" -eq 0 ]]; then
    tests_passed=true
  fi

  local next_state=ready_for_review
  if [[ "$worker_exit" -ne 0 ]]; then
    next_state=blocked
  fi
  if [[ "$timed_out" == true && "$WORKER_AUTO_RESUME_TIMEOUT" == "1" && "$attempt" -lt "$WORKER_MAX_TIMEOUT_RESUMES" ]]; then
    next_state=queued
    echo "Requeueing $id after timeout attempt $attempt; max timeout resumes: $WORKER_MAX_TIMEOUT_RESUMES"
  fi

  if [[ "$next_state" == "ready_for_review" ]]; then
    run_reviewers "$job" "$status_file" "$id" "$attempt" "$worktree" "$base_ref" "$final_commit"
  fi

  update_status "$status_file" \
    state="$next_state" \
    attempt="$attempt" \
    worker_exit="$worker_exit" \
    timed_out="$timed_out" \
    worker_error="$worker_error" \
    auto_resume_timeout="$WORKER_AUTO_RESUME_TIMEOUT" \
    test_exit="$test_exit" \
    tests_passed="$tests_passed" \
    commit="$final_commit" \
    report="$job/report.md"

  cleanup_current_lock
}

while true; do
  found=0
  shopt -s nullglob
  for status_file in .ai/jobs/J*/status.json; do
    state="$(jq -r '.state // ""' "$status_file")"
    if [[ "$state" == "queued" || "$state" == "rejected" ]]; then
      found=1
      process_job "$(dirname "$status_file")"
    fi
  done
  shopt -u nullglob

  if [[ "$found" -eq 0 ]]; then
    sleep "$POLL_SECONDS"
  fi
done
