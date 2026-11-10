#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$ROOT_DIR/backend"
exec uv run python -m app.cli sync
