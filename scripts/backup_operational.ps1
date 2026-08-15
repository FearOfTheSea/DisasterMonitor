param([string]$BackupName = (Get-Date -Format 'yyyyMMdd-HHmmss'))

$ErrorActionPreference = 'Stop'
if ($BackupName -notmatch '^[A-Za-z0-9_-]{1,80}$') {
  throw 'BackupName must contain only letters, numbers, underscore, or hyphen.'
}

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$LocalBackupRoot = Join-Path $RepositoryRoot 'data\backups'
New-Item -ItemType Directory -Path $LocalBackupRoot -Force | Out-Null
$DatabaseFile = "$BackupName-postgres.dump"
$BlobFile = "$BackupName-blobs.tar.gz"

Set-Location -LiteralPath $RepositoryRoot
docker compose stop api scheduler worker
try {
  docker compose exec -T postgres pg_dump --format=custom --file="/backups/$DatabaseFile" --username=disastermonitor --dbname=disastermonitor
  docker compose run --rm backup-tool sh -c "tar -czf /backups/$BlobFile -C /blobs ."
  docker compose cp "postgres:/backups/$DatabaseFile" (Join-Path $LocalBackupRoot $DatabaseFile)
  docker compose cp "postgres:/backups/$BlobFile" (Join-Path $LocalBackupRoot $BlobFile)
} finally {
  docker compose start api scheduler worker
}

$DatabaseHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $LocalBackupRoot $DatabaseFile)).Hash.ToLowerInvariant()
$BlobHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $LocalBackupRoot $BlobFile)).Hash.ToLowerInvariant()
@{
  schema_version = 'dm.operational-backup.v1'
  created_at_utc = (Get-Date).ToUniversalTime().ToString('o')
  database = @{ file = $DatabaseFile; sha256 = "sha256:$DatabaseHash" }
  blobs = @{ file = $BlobFile; sha256 = "sha256:$BlobHash" }
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $LocalBackupRoot "$BackupName-manifest.json") -Encoding utf8

Write-Output "Backup written to $LocalBackupRoot"
