#!/usr/bin/env bash
# Delete app backups older than BACKUP_RETENTION_DAYS (default 14), always keeping the newest BACKUP_MIN_KEEP (default 3).
set -euo pipefail
dir="${1:?Usage: backup-prune.sh BACKUP_DIR}"
days="${BACKUP_RETENTION_DAYS:-14}"
min_keep="${BACKUP_MIN_KEEP:-3}"
[[ "$days" =~ ^[0-9]+$ && "$min_keep" =~ ^[0-9]+$ ]] || { echo 'Retention values must be integers' >&2; exit 2; }
[[ -d "$dir" ]] || exit 0
count=0
while IFS= read -r file; do
  [[ -f "$file" && ! -L "$file" && "${file##*/}" =~ ^backup-[0-9]{8}-[0-9]{6}\.tar\.gz$ ]] || continue
  count=$((count + 1))
  if (( count > 10#$min_keep )) && [[ -n "$(find "$file" -maxdepth 0 -mtime +"$days")" ]]; then
    rm -f -- "$file"
    echo "Pruned $(basename "$file")"
  fi
done < <(ls -1t "$dir"/backup-????????-??????.tar.gz 2>/dev/null || true)
