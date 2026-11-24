<#
.SYNOPSIS
    Daily backup of Data Collector: MongoDB database, artifacts and deployment secrets.

.DESCRIPTION
    Writes to <DataRoot>\backups (Administrators/SYSTEM only):
        db-<ts>.archive.gz        mongodump --gzip --archive of the data_collector database
        artifacts-<ts>.zip        uploaded imports and generated exports
        secrets-<ts>.env          copy of datacollector.env (JWT/session secrets, OAuth RSA key)
    Deletes backups older than -RetentionDays. Copy this folder off the server (encrypted)
    for disaster recovery: a backup on the same disk does not survive losing the disk.

    Restore (into a NEW database name first, verify, then switch):
        mongorestore --gzip --archive=db-<ts>.archive.gz --nsFrom "data_collector.*" --nsTo "data_collector_restore.*"
#>
param(
    [string]$DataRoot = 'C:\ProgramData\DataCollector',
    [string]$MongoTools = 'C:\mongodb-database-tools-windows-x86_64-100.20.0\bin',
    [string]$MongoUri = 'mongodb://127.0.0.1:27017/',
    [string]$Database = 'data_collector',
    [int]$RetentionDays = 14
)
$ErrorActionPreference = 'Stop'
$dst = Join-Path $DataRoot 'backups'
New-Item -ItemType Directory -Force $dst | Out-Null
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $dst 'backup.log.txt'
function Log([string]$m) { Add-Content $log "$(Get-Date -Format s)  $m" }

try {
    $db = Join-Path $dst "db-$ts.archive.gz"
    # mongodump logs progress on stderr; run via cmd so PowerShell 5.1 does not turn it into errors
    $out = cmd /c "`"$MongoTools\mongodump.exe`" --uri $MongoUri --db $Database --gzip `"--archive=$db`" 2>&1"
    if ($LASTEXITCODE -ne 0) { throw "mongodump failed: $($out | Select-Object -Last 3)" }

    $art = Join-Path $DataRoot 'artifacts'
    if (Get-ChildItem $art -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 1) {
        Compress-Archive -Path "$art\*" -DestinationPath (Join-Path $dst "artifacts-$ts.zip") -CompressionLevel Optimal
    }
    Copy-Item (Join-Path $DataRoot 'secrets\datacollector.env') (Join-Path $dst "secrets-$ts.env")

    $cutoff = (Get-Date).AddDays(-$RetentionDays)
    Get-ChildItem $dst -File | Where-Object { $_.Name -match '^(db|artifacts|secrets)-' -and $_.LastWriteTime -lt $cutoff } | Remove-Item -Force
    Log "OK db=$([math]::Round((Get-Item $db).Length/1KB))KB"
} catch {
    Log "FAILED $($_.Exception.Message)"
    throw
}
