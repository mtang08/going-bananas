#!/bin/bash
set -euo pipefail
export PATH="/opt/homebrew/opt/postgresql@17/bin:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
root="$(cd "$(dirname "$0")" && pwd -P)"
exec python3 "$root/scripts/dashboard-login.py" "$@"
