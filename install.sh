#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-.}"
TARGET_DIR="$(cd "$TARGET_DIR" && pwd)"
OVERWRITE="${AI_WORKFLOW_OVERWRITE:-0}"

if [[ ! -d "$TARGET_DIR/.git" ]]; then
  echo "target is not a Git repository root: $TARGET_DIR" >&2
  exit 1
fi

copy_file() {
  local relative="$1"
  local source="$SOURCE_DIR/$relative"
  local target="$TARGET_DIR/$relative"

  if [[ -e "$target" && "$OVERWRITE" != "1" ]]; then
    echo "skip existing $relative"
    return 0
  fi

  mkdir -p "$(dirname "$target")"
  cp "$source" "$target"
  echo "installed $relative"
}

merge_gitignore() {
  local source="$SOURCE_DIR/.gitignore"
  local target="$TARGET_DIR/.gitignore"
  touch "$target"
  while IFS= read -r line; do
    if [[ -z "$line" ]]; then
      continue
    fi
    if ! grep -Fxq "$line" "$target"; then
      printf '%s\n' "$line" >>"$target"
      echo "added .gitignore entry: $line"
    fi
  done <"$source"
}

files=(
  "AGENTS.md"
  ".ai/README.md"
  ".ai/commit_docs/.gitkeep"
  ".ai/jobs/.gitkeep"
  ".ai/supervisor/commit_policy.md"
  ".ai/supervisor/design_prompt.md"
  ".ai/supervisor/job_template.md"
  ".ai/supervisor/ledger.md"
  ".ai/supervisor/human_reviews/.gitkeep"
  ".ai/supervisor/milestone_review_template.md"
  ".ai/supervisor/modulator_protocol.md"
  ".ai/supervisor/project_brief.md"
  ".ai/supervisor/review_checklist.md"
  ".ai/supervisor/roadmap.md"
  ".ai/supervisor/skill_decisions.md"
  ".ai/supervisor/supervisor_protocol.md"
  ".ai/supervisor/workflow_improvement_queue.md"
  ".ai/supervisor_runs/.gitkeep"
  "agent_wrappers/README.md"
  "agent_wrappers/codex/wrapper.json"
  "agent_wrappers/cursor-agent/wrapper.json"
  "docs/ai_supervisor_worker_workflow.tex"
  "gui/app.css"
  "gui/app.js"
  "gui/index.html"
  "scripts/_workflow_wrapper.py"
  "scripts/_workflow_wrapper.sh"
  "scripts/agent_wrapper.py"
  "scripts/analyze_reviewer_reports.py"
  "scripts/check_attempt_consistency.py"
  "scripts/check_job_progress_gate.py"
  "scripts/create_commit_doc.py"
  "scripts/create_job.py"
  "scripts/collect_agent_metrics.py"
  "scripts/commit_workflow_records.py"
  "scripts/check_reviewer_coverage.py"
  "scripts/cursor_stream_to_text.py"
  "scripts/extract_worker_handoff.py"
  "scripts/filter_allowed_artifacts.py"
  "scripts/human_milestone_review.py"
  "scripts/integrate_job.py"
  "scripts/list_skills.py"
  "scripts/modulator_loop.sh"
  "scripts/prune_accepted_job_refs.py"
  "scripts/record_workflow_event.py"
  "scripts/record_workflow_improvement.py"
  "scripts/render_worker_report.py"
  "scripts/summarize_agent_metrics.py"
  "scripts/summarize_progress_accounting.py"
  "scripts/summarize_jobs.py"
  "scripts/supervisor_loop.sh"
  "scripts/test_analyze_reviewer_reports.py"
  "scripts/test_check_job_progress_gate.py"
  "scripts/test_summarize_progress_accounting.py"
  "scripts/test_update_job_status.py"
  "scripts/transition_job.py"
  "scripts/update_job_status.py"
  "scripts/worker_loop.sh"
  "scripts/workflow_gui.py"
  "skills/attempt-artifact-consistency/SKILL.md"
  "skills/cursor-worker-dispatch/SKILL.md"
  "skills/numerical-test-design/SKILL.md"
  "skills/paper-equation-implementation/SKILL.md"
  "skills/performance-portability-review/SKILL.md"
  "skills/scientific-code-review/SKILL.md"
  "scripts/reviewer_report_parsing.py"
  "scripts/check_autonomy_boundary.py"
  "scripts/orchestrator.py"
  "scripts/consensus_core.py"
  "scripts/lib/agent_run.sh"
  "scripts/architect_core.py"
  "scripts/architect.py"
  "scripts/check_spec_completeness.py"
  "scripts/architect_compile.py"
  "scripts/aiflow.py"
  "scripts/test_consensus_core.py"
  "scripts/test_orchestrator.py"
  "scripts/test_architect_core.py"
  "scripts/test_architect.py"
  "agent_wrappers/panels/default.json"
  "agent_wrappers/panels/reviewer.json"
  "agent_wrappers/panels/supervisor.json"
  "agent_wrappers/panels/spec.json"
  ".ai/supervisor/consensus_policy.md"
  "project.yaml.example"
)

for file in "${files[@]}"; do
  copy_file "$file"
done

merge_gitignore
chmod +x \
  "$TARGET_DIR/scripts/_workflow_wrapper.sh" \
  "$TARGET_DIR/scripts/_workflow_wrapper.py" \
  "$TARGET_DIR/scripts/agent_wrapper.py" \
  "$TARGET_DIR/scripts/commit_workflow_records.py" \
  "$TARGET_DIR/scripts/analyze_reviewer_reports.py" \
  "$TARGET_DIR/scripts/check_attempt_consistency.py" \
  "$TARGET_DIR/scripts/check_job_progress_gate.py" \
  "$TARGET_DIR/scripts/check_reviewer_coverage.py" \
  "$TARGET_DIR/scripts/extract_worker_handoff.py" \
  "$TARGET_DIR/scripts/filter_allowed_artifacts.py" \
  "$TARGET_DIR/scripts/integrate_job.py" \
  "$TARGET_DIR/scripts/record_workflow_event.py" \
  "$TARGET_DIR/scripts/render_worker_report.py" \
  "$TARGET_DIR/scripts/summarize_progress_accounting.py" \
  "$TARGET_DIR/scripts/transition_job.py" \
  "$TARGET_DIR/scripts/worker_loop.sh" \
  "$TARGET_DIR/scripts/supervisor_loop.sh" \
  "$TARGET_DIR/scripts/modulator_loop.sh" \
  "$TARGET_DIR/scripts/human_milestone_review.py" \
  "$TARGET_DIR/scripts/list_skills.py" \
  "$TARGET_DIR/scripts/workflow_gui.py" \
  "$TARGET_DIR/scripts/check_autonomy_boundary.py" \
  "$TARGET_DIR/scripts/orchestrator.py" \
  "$TARGET_DIR/scripts/architect.py" \
  "$TARGET_DIR/scripts/check_spec_completeness.py" \
  "$TARGET_DIR/scripts/architect_compile.py" \
  "$TARGET_DIR/scripts/aiflow.py"

echo "AI workflow installation complete."
