#!/usr/bin/env bash
# Source from repository-local runners; never print secret environment values.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/opt/homebrew/opt/node@22/bin:/opt/homebrew/opt/postgresql@17/bin:/opt/homebrew/bin:$PATH"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT_DIR/private/cache/uv}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$ROOT_DIR/private/cache/playwright}"
# A nested repo runner must keep the explicit mode and database selected by with-mode.
if [[ "${GB_MODE_ROOT:-}" != "$ROOT_DIR" && -f "$ROOT_DIR/.env" ]]; then
  # Treat the database, mode and storage directory as one destination. An inherited
  # partial override must never be silently redirected to the configured athlete.
  gb_requested_backend="${GOING_BANANAS_BACKEND:-}"
  gb_requested_mode="${APP_MODE:-}"
  gb_requested_db="${DATABASE_URL:-}"
  gb_requested_dir="${PRIVATE_DIR:-}"
  set -a
  source "$ROOT_DIR/.env"
  set +a
  if [[ -n "$gb_requested_backend" ]]; then
    export GOING_BANANAS_BACKEND="$gb_requested_backend"
  fi
  if [[ -n "$gb_requested_mode" && -n "$gb_requested_db" && -n "$gb_requested_dir" ]]; then
    export APP_MODE="$gb_requested_mode" DATABASE_URL="$gb_requested_db" PRIVATE_DIR="$gb_requested_dir"
  elif [[ ( -n "$gb_requested_mode" && "$gb_requested_mode" != "${APP_MODE:-}" ) ||
          ( -n "$gb_requested_db" && "$gb_requested_db" != "${DATABASE_URL:-}" ) ||
          ( -n "$gb_requested_dir" && "$gb_requested_dir" != "${PRIVATE_DIR:-}" ) ]]; then
    echo 'Partial runtime override conflicts with .env. Use scripts/with-mode, or set APP_MODE, DATABASE_URL and PRIVATE_DIR together.' >&2
    exit 2
  fi
  unset gb_requested_backend gb_requested_mode gb_requested_db gb_requested_dir
fi
cd "$ROOT_DIR"
