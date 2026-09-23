param(
  [string]$Archive = ('operational-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.tar.gz')
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$BackupRoot = Join-Path $RepositoryRoot 'data\backups'
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
$ArchiveName = Split-Path -Leaf $Archive
Set-Location -LiteralPath $RepositoryRoot
docker compose stop api scheduler worker
try {
  docker compose --profile tools run --rm backup-tool backup `
    --archive "/backups/$ArchiveName" `
    --operational-blobs /operational-blobs `
    --event-media /event-media `
    --ground-imagery /ground-imagery `
    --field-reports /field-reports `
    --operator-workspace /operator-workspace `
    --writers-paused
} finally {
  docker compose start api scheduler worker | Out-Null
}
