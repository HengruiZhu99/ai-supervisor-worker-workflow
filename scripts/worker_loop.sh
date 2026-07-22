#!/usr/bin/env bash
# Deprecated finite compatibility shim; remove after 0.6.0 / 2027-01-31.

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
TOOL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKER_MODEL="${WORKER_MODEL:-gpt-5.6-sol}"
WORKER_TIMEOUT="${WORKER_TIMEOUT:-3600}"
TEST_TIMEOUT="${TEST_TIMEOUT:-1800}"
MAX_TASKS="${AIFLOW_MAX_TASKS:-25}"
MAX_ATTEMPTS="${AIFLOW_MAX_ATTEMPTS:-3}"
MAX_IDLE="${AIFLOW_MAX_IDLE:-900}"

echo "warning: scripts/worker_loop.sh is deprecated; use aiflow run resume" >&2
export AIFLOW_COMPAT_MODEL="$WORKER_MODEL"
export AIFLOW_COMPAT_TEST_TIMEOUT="$TEST_TIMEOUT"

CLI=(aiflow)
if [[ -x "$TOOL_ROOT/bin/aiflow" ]]; then CLI=("$TOOL_ROOT/bin/aiflow"); fi
exec "${CLI[@]}" --project-root "$ROOT" controller run \
  --mode orchestrated --parent-sandbox workspace-write --compat-role worker \
  --max-wall-time "$WORKER_TIMEOUT" --max-tasks "$MAX_TASKS" \
  --max-attempts "$MAX_ATTEMPTS" --max-idle "$MAX_IDLE" "$@"
