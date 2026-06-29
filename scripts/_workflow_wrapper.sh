#!/usr/bin/env bash
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SCRIPT_NAME="$(basename "$0")"
if [[ "$SCRIPT_NAME" == "_workflow_wrapper.sh" ]]; then
  if [[ "$#" -lt 1 ]]; then
    echo "usage: _workflow_wrapper.sh <workflow-script-name> [args...]" >&2
    exit 2
  fi
  SCRIPT_NAME="$1"
  shift
fi

candidates=()
if [[ -n "${AI_WORKFLOW_PACKAGE_ROOT:-}" ]]; then
  candidates+=("$AI_WORKFLOW_PACKAGE_ROOT/scripts/$SCRIPT_NAME")
fi
candidates+=("$ROOT/external/ai-supervisor-worker-workflow/scripts/$SCRIPT_NAME")

COMMON_DIR="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
if [[ "$(basename "$COMMON_DIR")" == ".git" ]]; then
  MAIN_ROOT="$(dirname "$COMMON_DIR")"
  if [[ "$MAIN_ROOT" != "$ROOT" ]]; then
    candidates+=("$MAIN_ROOT/external/ai-supervisor-worker-workflow/scripts/$SCRIPT_NAME")
  fi
fi

for target in "${candidates[@]}"; do
  if [[ -x "$target" ]]; then
    exec "$target" "$@"
  fi
done

{
  echo "workflow package script not found or not executable; checked:"
  printf -- '- %s\n' "${candidates[@]}"
} >&2
exit 1
