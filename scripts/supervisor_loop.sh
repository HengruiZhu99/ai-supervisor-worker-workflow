#!/usr/bin/env bash
# Deprecated finite compatibility shim; remove after 0.6.0 / 2027-01-31.

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
TOOL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPERVISOR_MODEL="${SUPERVISOR_MODEL:-gpt-5.6-sol}"
MAX_WALL="${AIFLOW_MAX_WALL_TIME:-3600}"
MAX_TASKS="${AIFLOW_MAX_TASKS:-25}"
MAX_ATTEMPTS="${AIFLOW_MAX_ATTEMPTS:-3}"
MAX_IDLE="${AIFLOW_MAX_IDLE:-900}"

echo "warning: scripts/supervisor_loop.sh is deprecated; use aiflow run resume" >&2
export AIFLOW_COMPAT_MODEL="$SUPERVISOR_MODEL"

CLI=(aiflow)
if [[ -x "$TOOL_ROOT/bin/aiflow" ]]; then CLI=("$TOOL_ROOT/bin/aiflow"); fi
exec "${CLI[@]}" --project-root "$ROOT" controller run \
  --mode orchestrated --parent-sandbox workspace-write --compat-role supervisor \
  --max-wall-time "$MAX_WALL" --max-tasks "$MAX_TASKS" \
  --max-attempts "$MAX_ATTEMPTS" --max-idle "$MAX_IDLE" "$@"
