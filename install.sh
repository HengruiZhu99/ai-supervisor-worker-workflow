#!/usr/bin/env bash
set -euo pipefail

# Deprecated compatibility installer. The runtime stays in this distribution;
# only the selected project profile, lock, and small skills are transacted into
# the target. Set AIFLOW_PROFILE to solo|science|hpc|orchestrated|full.
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-.}"
PROFILE="${AIFLOW_PROFILE:-solo}"

echo "warning: install.sh is deprecated; use 'aiflow project init --profile $PROFILE'" >&2
exec "$SOURCE_DIR/bin/aiflow" \
  --project-root "$TARGET_DIR" \
  project init \
  --profile "$PROFILE"
