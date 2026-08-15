param(
  [Parameter(Mandatory = $true)][string]$BackupName,
  [Parameter(Mandatory = $true)][string]$ConfirmRestore
)

$ErrorActionPreference = 'Stop'
if ($BackupName -notmatch '^[A-Za-z0-9_-]{1,80}$') {
  throw 'BackupName must contain only letters, numbers, underscore, or hyphen.'
}
if ($ConfirmRestore -ne 'REPLACE_OPERATIONAL_STATE') {
  throw 'Pass -ConfirmRestore REPLACE_OPERATIONAL_STATE to authorize replacement.'
}

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$LocalBackupRoot = (Resolve-Path (Join-Path $RepositoryRoot 'data\backups')).Path
$ManifestPath = (Resolve-Path (Join-Path $LocalBackupRoot "$BackupName-manifest.json")).Path
if (-not $ManifestPath.StartsWith($LocalBackupRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw 'Backup path escaped the repository backup directory.'
}
$Manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
$DatabasePath = (Resolve-Path (Join-Path $LocalBackupRoot $Manifest.database.file)).Path
$BlobPath = (Resolve-Path (Join-Path $LocalBackupRoot $Manifest.blobs.file)).Path
$DatabaseHash = 'sha256:' + (Get-FileHash -Algorithm SHA256 -LiteralPath $DatabasePath).Hash.ToLowerInvariant()
$BlobHash = 'sha256:' + (Get-FileHash -Algorithm SHA256 -LiteralPath $BlobPath).Hash.ToLowerInvariant()
if ($DatabaseHash -ne $Manifest.database.sha256 -or $BlobHash -ne $Manifest.blobs.sha256) {
  throw 'Backup checksum verification failed.'
}

Set-Location -LiteralPath $RepositoryRoot
docker compose stop api scheduler worker
try {
  docker compose cp $DatabasePath "postgres:/backups/$($Manifest.database.file)"
  docker compose cp $BlobPath "postgres:/backups/$($Manifest.blobs.file)"
  docker compose exec -T postgres pg_restore --clean --if-exists --exit-on-error --username=disastermonitor --dbname=disastermonitor "/backups/$($Manifest.database.file)"
  docker compose run --rm backup-tool sh -c "find /blobs -mindepth 1 -delete && tar -xzf /backups/$($Manifest.blobs.file) -C /blobs"
} finally {
  docker compose start api scheduler worker
}

Write-Output "Operational state restored from $BackupName"
