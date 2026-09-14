param(
  [Parameter(Mandatory = $true)][string]$Archive,
  [Parameter(Mandatory = $true)][string]$ConfirmRestore
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$BackupRoot = (Resolve-Path (Join-Path $RepositoryRoot 'data\backups')).Path
$ArchiveName = Split-Path -Leaf $Archive
$ArchivePath = Join-Path $BackupRoot $ArchiveName
if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf)) {
  throw "Backup archive was not found under data/backups: $ArchiveName"
}
Set-Location -LiteralPath $RepositoryRoot
docker compose stop api scheduler worker
try {
  docker compose --profile tools run --rm backup-tool restore `
    --archive "/backups/$ArchiveName" `
    --confirm $ConfirmRestore `
    --operational-blobs /operational-blobs `
    --event-media /event-media `
    --ground-imagery /ground-imagery `
    --writers-paused
} finally {
  docker compose start api scheduler worker | Out-Null
}
