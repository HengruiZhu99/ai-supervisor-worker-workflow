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
  ".ai/supervisor/project_brief.md"
  ".ai/supervisor/review_checklist.md"
  ".ai/supervisor/roadmap.md"
  ".ai/supervisor/supervisor_protocol.md"
  ".ai/supervisor_runs/.gitkeep"
  "gui/app.css"
  "gui/app.js"
  "gui/index.html"
  "scripts/create_commit_doc.py"
  "scripts/create_job.py"
  "scripts/cursor_stream_to_text.py"
  "scripts/human_milestone_review.py"
  "scripts/summarize_jobs.py"
  "scripts/supervisor_loop.sh"
  "scripts/update_job_status.py"
  "scripts/worker_loop.sh"
  "scripts/workflow_gui.py"
  "skills/cursor-worker-dispatch/SKILL.md"
  "skills/numerical-test-design/SKILL.md"
  "skills/paper-equation-implementation/SKILL.md"
  "skills/performance-portability-review/SKILL.md"
  "skills/scientific-code-review/SKILL.md"
)

for file in "${files[@]}"; do
  copy_file "$file"
done

merge_gitignore
chmod +x \
  "$TARGET_DIR/scripts/worker_loop.sh" \
  "$TARGET_DIR/scripts/supervisor_loop.sh" \
  "$TARGET_DIR/scripts/human_milestone_review.py" \
  "$TARGET_DIR/scripts/workflow_gui.py"

echo "AI workflow installation complete."
