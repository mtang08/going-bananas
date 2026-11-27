#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/env.sh"
if [[ -d "$ROOT_DIR/private/postgres" ]]; then
  python3 "$ROOT_DIR/scripts/local-db.py"
fi
"$ROOT_DIR/scripts/backend-cli" sync
backup_dir="${PRIVATE_DIR:?PRIVATE_DIR is not set}/backups"
if ! compgen -G "$backup_dir/backup-$(date +%Y%m%d)-*.tar.gz" >/dev/null; then
  "$ROOT_DIR/scripts/backend-cli" backup "$backup_dir/backup-$(date +%Y%m%d-%H%M%S).tar.gz"
fi
"$ROOT_DIR/scripts/backup-prune.sh" "$backup_dir"
