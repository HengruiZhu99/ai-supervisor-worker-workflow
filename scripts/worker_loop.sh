#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

CURSOR_TIMEOUT="${CURSOR_TIMEOUT:-3600}"
CURSOR_MODEL="${CURSOR_MODEL:-gpt-5.5-high}"
CURSOR_AGENT_EXTRA_ARGS="${CURSOR_AGENT_EXTRA_ARGS:-}"
POLL_SECONDS="${POLL_SECONDS:-5}"
CURRENT_LOCK=""

cleanup_current_lock() {
  if [[ -n "${CURRENT_LOCK:-}" ]]; then
    rmdir "$CURRENT_LOCK" 2>/dev/null || true
    CURRENT_LOCK=""
  fi
}

trap cleanup_current_lock EXIT INT TERM

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
  # Set CURSOR_AGENT_EXTRA_ARGS for local flags such as --force if desired.
  # shellcheck disable=SC2086
  timeout "$CURSOR_TIMEOUT" \
    cursor-agent -p --trust --workspace "$worktree" --output-format text --model "$CURSOR_MODEL" $CURSOR_AGENT_EXTRA_ARGS "$(cat "$prompt_file")"
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
  local worker_exit=0
  set +e
  run_cursor_agent "$ROOT/$worktree" "$ROOT/$prompt_file" 2> >(tee "$cursor_err" >&2) | tee "$cursor_out"
  worker_exit=${PIPESTATUS[0]}
  set -e

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

  update_status "$status_file" \
    state="$next_state" \
    attempt="$attempt" \
    worker_exit="$worker_exit" \
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
