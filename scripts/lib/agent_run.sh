#!/usr/bin/env bash
#========================================================================================
# BBHK spectral numerical relativity code
# Copyright(C) 2026 Hengrui Zhu
#========================================================================================

# Shared agent-run dispatch for the workflow loops.
#
# Historically the supervisor and modulator loops each carried a near-identical
# block that ran `agent_wrapper.py`, streamed cursor-agent JSON through
# `cursor_stream_to_text.py`, and captured the exit code. Keeping two copies in
# sync was error-prone. This is the single source of truth for that dispatch.
#
# The caller still owns timing, metrics collection, and any `set +e/-e` region,
# because those differ slightly per role. This helper only runs the agent and
# reports the exit code via the global AGENT_RUN_EXIT.
#
# Requirements in the sourcing script:
#   - SCRIPT_DIR  : absolute path to the scripts/ directory.
#   - cwd is the repository root (the loops `cd "$ROOT"`).
#
# Usage:
#   run_streamed_agent ROLE WRAPPER MODEL WORKSPACE PROMPT_FILE \
#       EXTRA_ARGS REASONING_EFFORT LOG_FILE STREAM_FILE
#
# For cursor-agent the run uses --output-format stream-json, tees the raw stream
# to STREAM_FILE, and appends a human-readable conversion to LOG_FILE. For any
# other wrapper it writes combined stdout/stderr to LOG_FILE and STREAM_FILE is
# ignored. AGENT_RUN_EXIT is set to the agent's exit code in both paths.

run_streamed_agent() {
  local role="$1"
  local wrapper="$2"
  local model="$3"
  local workspace="$4"
  local prompt_file="$5"
  local extra_args="$6"
  local reasoning="$7"
  local log_file="$8"
  local stream_file="$9"

  if [[ "$wrapper" == "cursor-agent" ]]; then
    # stream-json gives exact token usage; the text converter keeps the log
    # human-readable for the GUI tail.
    python3 "$SCRIPT_DIR/agent_wrapper.py" run \
      --role "$role" \
      --wrapper "$wrapper" \
      --model "$model" \
      --workspace "$workspace" \
      --prompt-file "$prompt_file" \
      --reasoning-effort "$reasoning" \
      --output-format stream-json \
      --extra-args="$extra_args" 2>>"$log_file" \
      | tee "$stream_file" \
      | python3 "$SCRIPT_DIR/cursor_stream_to_text.py" >>"$log_file"
    AGENT_RUN_EXIT=${PIPESTATUS[0]}
  else
    python3 "$SCRIPT_DIR/agent_wrapper.py" run \
      --role "$role" \
      --wrapper "$wrapper" \
      --model "$model" \
      --workspace "$workspace" \
      --prompt-file "$prompt_file" \
      --reasoning-effort "$reasoning" \
      --extra-args="$extra_args" >"$log_file" 2>&1
    AGENT_RUN_EXIT=$?
  fi
}
