#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_root"
archive=${1:?"Usage: $0 ARCHIVE REPLACE_OPERATIONAL_STATE"}
confirmation=${2:-}

if [ "$confirmation" != "REPLACE_OPERATIONAL_STATE" ]; then
  echo "Restore requires the exact confirmation REPLACE_OPERATIONAL_STATE." >&2
  exit 2
fi

archive_name=$(basename -- "$archive")
if [ ! -f "$repository_root/data/backups/$archive_name" ]; then
  echo "Backup archive was not found under data/backups: $archive_name" >&2
  exit 2
fi

restart_writers() {
  docker compose start api scheduler worker >/dev/null
}
docker compose stop api scheduler worker
trap restart_writers EXIT INT TERM
docker compose --profile tools run --rm backup-tool restore \
  --archive "/backups/$archive_name" \
  --confirm "$confirmation" \
  --operational-blobs /operational-blobs \
  --event-media /event-media \
  --ground-imagery /ground-imagery \
  --writers-paused
