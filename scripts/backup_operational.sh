#!/usr/bin/env sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repository_root"
timestamp=$(date -u +%Y%m%d-%H%M%S)
archive=${1:-"$repository_root/data/backups/operational-$timestamp.tar.gz"}
archive_name=$(basename -- "$archive")
mkdir -p "$repository_root/data/backups"

restart_writers() {
  docker compose start api scheduler worker >/dev/null
}
docker compose stop api scheduler worker
trap restart_writers EXIT INT TERM
docker compose --profile tools run --rm backup-tool backup \
  --archive "/backups/$archive_name" \
  --operational-blobs /operational-blobs \
  --event-media /event-media \
  --ground-imagery /ground-imagery \
  --field-reports /field-reports \
  --operator-workspace /operator-workspace \
  --writers-paused
