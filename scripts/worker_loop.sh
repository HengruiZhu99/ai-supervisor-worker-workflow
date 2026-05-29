#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOW_PACKAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export AI_WORKFLOW_PACKAGE_ROOT="${AI_WORKFLOW_PACKAGE_ROOT:-$WORKFLOW_PACKAGE_ROOT}"
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
CURSOR_REVIEWER_MAX_RELAUNCHES="${CURSOR_REVIEWER_MAX_RELAUNCHES:-1}"
WORKER_AUTO_RESUME_TIMEOUT="${WORKER_AUTO_RESUME_TIMEOUT:-0}"
WORKER_MAX_TIMEOUT_RESUMES="${WORKER_MAX_TIMEOUT_RESUMES:-1}"
WORKER_AUTO_RELAUNCH_FAILURE="${WORKER_AUTO_RELAUNCH_FAILURE:-1}"
WORKER_MAX_FAILURE_RESUMES="${WORKER_MAX_FAILURE_RESUMES:-2}"
POLL_SECONDS="${POLL_SECONDS:-5}"
CURRENT_LOCK=""
HUMAN_GATE=".ai/supervisor/HUMAN_REVIEW_REQUIRED.md"
STRUCTURAL_REQUEST=".ai/supervisor/STRUCTURAL_CHANGE_REQUESTED.md"
HUMAN_REVIEW_ACTION_REQUEST=".ai/supervisor/HUMAN_REVIEW_ACTION_REQUESTED.md"

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

CURSOR_MODEL="$(normalize_cursor_model "$CURSOR_MODEL")"
CURSOR_REVIEWER_A_MODEL="$(normalize_cursor_model "$CURSOR_REVIEWER_A_MODEL")"
CURSOR_REVIEWER_B_MODEL="$(normalize_cursor_model "$CURSOR_REVIEWER_B_MODEL")"

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

workflow_commit="$(git -C "$SCRIPT_DIR/.." rev-parse --short HEAD 2>/dev/null || git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "workflow_commit=$workflow_commit"
echo "cursor_model=$CURSOR_MODEL"
echo "cursor_reviewer_a_model=$CURSOR_REVIEWER_A_MODEL"
echo "cursor_reviewer_b_model=$CURSOR_REVIEWER_B_MODEL"

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
    echo "- Diffstat: $ROOT/$job/diffstat.attempt-$attempt.txt"
    echo "- Changed files: $ROOT/$changed_files_file"
    echo "- Patch: $ROOT/$job/diff.attempt-$attempt.patch"
    echo "- Test log: $ROOT/$job/test.attempt-$attempt.log"
    echo "- Commit docs: $ROOT/.ai/commit_docs/"
    echo "- Existing skills: run 'python3 scripts/list_skills.py' in the worktree if needed. The environment variable AI_WORKFLOW_PACKAGE_ROOT is set to $AI_WORKFLOW_PACKAGE_ROOT."
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
    echo "Use commands such as 'git diff --name-only $base_sha..$final_commit', 'git diff $base_sha..$final_commit -- <path>', and direct source reads from the worktree."
    echo "If the diff is too large to review comprehensively within this reviewer pass, recommend revise/split; do not recommend acceptance for partially reviewed work."
    echo "Cross-check the worker report, test log, commit docs, and actual code. The actual diff and worktree are the source of truth."
    echo
    echo "Include this machine-checkable fenced YAML block exactly once:"
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
    echo "8. Suggested supervisor decision rationale"
    echo "9. Skill suggestion review: whether the worker's suggested skills are useful, duplicate existing skills, and should be project-specific, general workflow skills, deferred, or rejected. Run 'python3 scripts/list_skills.py' if needed."
  } >"$prompt_file"
}

run_one_reviewer() {
  local role="$1"
  local model="$2"
  local job="$3"
  local id="$4"
  local attempt="$5"
  local worktree="$6"
  local base_sha="$7"
  local final_commit="$8"
  local reviews_dir="$job/reviews"

  mkdir -p "$reviews_dir"

  local prompt_file="$reviews_dir/$role.prompt.attempt-$attempt.md"
  local review_out="$reviews_dir/$role.attempt-$attempt.md"
  local review_err="$reviews_dir/$role.stderr.attempt-$attempt.log"
  local review_stream="$reviews_dir/$role.stream.attempt-$attempt.jsonl"
  local reviewer_exit=0

  write_reviewer_prompt "$role" "$job" "$id" "$attempt" "$worktree" "$base_sha" "$final_commit" "$prompt_file"

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
    reviewer_a_model="$CURSOR_REVIEWER_A_MODEL" \
    reviewer_b_model="$CURSOR_REVIEWER_B_MODEL"

  local try
  for ((try = 0; try <= CURSOR_REVIEWER_MAX_RELAUNCHES; try++)); do
    reviewer_a_exit=0
    run_one_reviewer "reviewer-a" "$CURSOR_REVIEWER_A_MODEL" "$job" "$id" "$attempt" "$worktree" "$base_sha" "$final_commit" || reviewer_a_exit=$?
    [[ "$reviewer_a_exit" -eq 0 ]] && break
    if [[ "$try" -lt "$CURSOR_REVIEWER_MAX_RELAUNCHES" ]]; then
      echo "Relaunching reviewer-a after exit $reviewer_a_exit (retry $((try + 1))/${CURSOR_REVIEWER_MAX_RELAUNCHES})"
    fi
  done
  for ((try = 0; try <= CURSOR_REVIEWER_MAX_RELAUNCHES; try++)); do
    reviewer_b_exit=0
    run_one_reviewer "reviewer-b" "$CURSOR_REVIEWER_B_MODEL" "$job" "$id" "$attempt" "$worktree" "$base_sha" "$final_commit" || reviewer_b_exit=$?
    [[ "$reviewer_b_exit" -eq 0 ]] && break
    if [[ "$try" -lt "$CURSOR_REVIEWER_MAX_RELAUNCHES" ]]; then
      echo "Relaunching reviewer-b after exit $reviewer_b_exit (retry $((try + 1))/${CURSOR_REVIEWER_MAX_RELAUNCHES})"
    fi
  done

  local coverage_exit=0
  python3 scripts/check_reviewer_coverage.py "$job/changed_files.attempt-$attempt.txt" \
    "$job/reviews/reviewer-a.attempt-$attempt.md" \
    "$job/reviews/reviewer-b.attempt-$attempt.md" \
    >"$job/reviews/coverage.attempt-$attempt.txt" 2>&1 || coverage_exit=$?

  update_status "$status_file" \
    reviewer_a_exit="$reviewer_a_exit" \
    reviewer_b_exit="$reviewer_b_exit" \
    reviewer_coverage_exit="$coverage_exit" \
    reviewers_complete="$([[ "$reviewer_a_exit" -eq 0 && "$reviewer_b_exit" -eq 0 && "$coverage_exit" -eq 0 ]] && echo true || echo false)" \
    reviewer_a_report="$job/reviews/reviewer-a.attempt-$attempt.md" \
    reviewer_b_report="$job/reviews/reviewer-b.attempt-$attempt.md"

  if [[ "$reviewer_a_exit" -eq 124 || "$reviewer_b_exit" -eq 124 ]]; then
    return 124
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

  local id base_ref base_sha branch test_command attempt worktree current_branch
  id="$(json_field "$status_file" id)"
  base_ref="$(json_field "$status_file" base_ref)"
  base_sha="$(json_field "$status_file" base_sha)"
  branch="$(json_field "$status_file" branch)"
  test_command="$(json_field "$status_file" test_command)"
  attempt="$(jq -r '(.attempt // 0) + 1' "$status_file")"
  worktree=".worktrees/$id"

  if [[ -z "$id" || -z "$base_ref" || -z "$branch" ]]; then
    update_status "$status_file" state=blocked worker_error="missing id, base_ref, or branch"
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
      git worktree add "$worktree" "$branch"
    else
      git worktree add -b "$branch" "$worktree" "$base_sha"
    fi
  fi

  update_status "$status_file" state=running attempt="$attempt" branch="$branch" base_sha="$base_sha" workflow_commit="$workflow_commit"

  local prompt_file="$job/worker_prompt.attempt-$attempt.md"
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
  local post_test_status="$job/post_test_status.attempt-$attempt.txt"
  git -C "$worktree" status --porcelain >"$post_test_status"
  local post_test_dirty=false
  local post_test_dirty_error=""
  if [[ -s "$post_test_status" ]]; then
    post_test_dirty=true
    post_test_dirty_error="worktree has uncommitted changes after tests; see $post_test_status"
  fi

  git -C "$worktree" diff --name-status "$base_sha..HEAD" >"$job/changed_files.attempt-$attempt.txt" || true
  git -C "$worktree" diff --stat "$base_sha..HEAD" >"$job/diffstat.attempt-$attempt.txt" || true
  git -C "$worktree" diff "$base_sha..HEAD" >"$job/diff.attempt-$attempt.patch" || true

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
    echo
    echo "## Base commit"
    echo "$base_sha"
    echo
    echo "## Changed files"
    cat "$job/changed_files.attempt-$attempt.txt"
    if [[ "$post_test_dirty" == true ]]; then
      echo
      echo "## Post-test dirty worktree"
      echo "$post_test_dirty_error"
    fi
  } >"$job/report.md"

  python3 scripts/create_commit_doc.py \
    --job-id "$id" \
    --attempt "$attempt" \
    --branch "$branch" \
    --base-sha "$base_sha" \
    --commit "$final_commit" \
    --test-command "$test_command" \
    --test-exit "$test_exit" \
    --test-log "$test_log" \
    --summary-file "$cursor_out" >/dev/null || true

  local tests_passed=false
  if [[ "$test_exit" -eq 0 ]]; then
    tests_passed=true
  fi

  local cursor_reported_success=false
  if grep -q '\[system success\]' "$cursor_out" 2>/dev/null; then
    cursor_reported_success=true
  fi

  local next_state=ready_for_review
  if [[ "$worker_exit" -ne 0 && "$cursor_reported_success" == true && "$tests_passed" == true && "$post_test_dirty" != true ]]; then
    worker_error="${worker_error:+$worker_error; }cursor-agent returned nonzero after reporting system success; continuing to reviewer stage"
    echo "$worker_error" | tee -a "$cursor_err" >&2
  elif [[ "$worker_exit" -ne 0 ]]; then
    next_state=blocked
  fi
  if [[ "$post_test_dirty" == true ]]; then
    next_state=blocked
    worker_error="${worker_error:+$worker_error; }$post_test_dirty_error"
  fi
  if [[ "$worker_exit" -ne 0 && "$timed_out" != true && "$post_test_dirty" != true && "$WORKER_AUTO_RELAUNCH_FAILURE" == "1" && "$attempt" -lt "$WORKER_MAX_FAILURE_RESUMES" ]]; then
    next_state=queued
    echo "Requeueing $id after worker failure attempt $attempt; max failure resumes: $WORKER_MAX_FAILURE_RESUMES"
  fi
  if [[ "$timed_out" == true && "$WORKER_AUTO_RESUME_TIMEOUT" == "1" && "$attempt" -lt "$WORKER_MAX_TIMEOUT_RESUMES" ]]; then
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
    tests_passed="$tests_passed" \
    post_test_dirty="$post_test_dirty" \
    post_test_status="$post_test_status" \
    changed_files="$job/changed_files.attempt-$attempt.txt" \
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

  if [[ ! -s "$job/changed_files.attempt-$attempt.txt" ]]; then
    git -C "$worktree" diff --name-status "$base_sha..$final_commit" >"$job/changed_files.attempt-$attempt.txt" || true
  fi
  if [[ ! -s "$job/diffstat.attempt-$attempt.txt" ]]; then
    git -C "$worktree" diff --stat "$base_sha..$final_commit" >"$job/diffstat.attempt-$attempt.txt" || true
  fi
  if [[ ! -s "$job/diff.attempt-$attempt.patch" ]]; then
    git -C "$worktree" diff "$base_sha..$final_commit" >"$job/diff.attempt-$attempt.patch" || true
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
  if [[ -f "$HUMAN_GATE" || -f "$STRUCTURAL_REQUEST" || -f "$HUMAN_REVIEW_ACTION_REQUEST" ]]; then
    sleep "$POLL_SECONDS"
    continue
  fi

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
