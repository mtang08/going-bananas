#!/usr/bin/env bash
# Source from repository-local runners; never print secret environment values.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/opt/homebrew/opt/node@22/bin:/opt/homebrew/opt/postgresql@17/bin:/opt/homebrew/bin:$PATH"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT_DIR/private/cache/uv}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$ROOT_DIR/private/cache/playwright}"
# A nested repo runner must keep the explicit mode and database selected by with-mode.
if [[ "${GB_MODE_ROOT:-}" != "$ROOT_DIR" && -f "$ROOT_DIR/.env" ]]; then
  set -a
  source "$ROOT_DIR/.env"
  set +a
fi
cd "$ROOT_DIR"
