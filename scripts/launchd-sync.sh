#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
if [[ -d "$ROOT_DIR/private/postgres" ]]; then
  python3 "$ROOT_DIR/scripts/local-db.py"
fi
cd "$ROOT_DIR/backend"
exec uv run python -m app.cli sync
