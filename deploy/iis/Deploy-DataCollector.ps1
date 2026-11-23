<#
.SYNOPSIS
    Build and activate a Data Collector release on IIS (direct Python FastCGI, no reverse proxy).

.DESCRIPTION
    Creates an immutable release folder  <SiteRoot>\releases\<yyyyMMdd-HHmmss>-<sha7>\
        app\       Python code snapshot (data_collector, deploy.iis.wsgi)
        venv\      dedicated virtual environment (non-editable install + wfastcgi)
        web-dist\  built Admin UI (Vite SPA)
    then switches the IIS site (web.config + FastCGI application) and the worker service to it.
    Keeps the newest -KeepReleases releases for rollback.

    Touches only: app pool + site "<SiteName>", its FastCGI application entries, the
    "<WorkerService>" Windows service, and folders under -SiteRoot / -DataRoot. Backs up the
    IIS configuration (appcmd add backup) before changing anything.

    Run from an elevated Windows PowerShell 5.1 prompt.

.EXAMPLE
    .\Deploy-DataCollector.ps1                 # build + activate current HEAD of the repo
    .\Deploy-DataCollector.ps1 -Rollback       # re-activate the previous release
#>
[CmdletBinding()]
param(
    [string]$RepoPath = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path,
    [string]$SiteName = 'DataCollector',
    [string]$HostName = 'data.devart.solutions',
    [string]$SiteRoot = 'C:\Sites\DataCollector',
    [string]$DataRoot = 'C:\ProgramData\DataCollector',
    [string]$BasePython = 'C:\Program Files\Python312\python.exe',
    [string]$WorkerService = 'DataCollectorWorker',
    [string]$Nssm = 'C:\tools\nssm\nssm.exe',
    [int]$KeepReleases = 3,
    [switch]$Rollback,
    [switch]$SkipWebBuild
)

$ErrorActionPreference = 'Stop'
Import-Module WebAdministration
$appcmd = "$env:windir\system32\inetsrv\appcmd.exe"
$EnvFile = Join-Path $DataRoot 'secrets\datacollector.env'
$PoolId = "IIS AppPool\$SiteName"
$WorkerId = "NT SERVICE\$WorkerService"
$Releases = Join-Path $SiteRoot 'releases'
$WwwRoot = Join-Path $SiteRoot 'wwwroot'

function Step([string]$m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Run([string]$cmd) {
    # Native tools write warnings to stderr; judge them by exit code only.
    $out = cmd /c "$cmd 2>&1"
    if ($LASTEXITCODE -ne 0) { $out | Select-Object -Last 30 | Write-Host; throw "Failed ($LASTEXITCODE): $cmd" }
    return $out
}

function Get-FastCgiArgs([string]$rel) {
    $py = Join-Path $rel 'venv\Scripts\python.exe'
    $wf = Join-Path $rel 'venv\Lib\site-packages\wfastcgi.py'
    return @{ Python = $py; Wfastcgi = $wf }
}

function Register-FastCgi([string]$rel) {
    $f = Get-FastCgiArgs $rel
    $exists = & $appcmd list config -section:system.webServer/fastCgi | Select-String -SimpleMatch "fullPath=`"$($f.Python)`""
    if (-not $exists) {
        Run "`"$appcmd`" set config -section:system.webServer/fastCgi /+`"[fullPath='$($f.Python)',arguments='$($f.Wfastcgi)',maxInstances='4',idleTimeout='1800',activityTimeout='300',requestTimeout='330',instanceMaxRequests='10000',protocol='NamedPipe',signalBeforeTerminateSeconds='10']`" /commit:apphost" | Out-Null
    }
}

function Unregister-FastCgi([string]$rel) {
    $f = Get-FastCgiArgs $rel
    $exists = & $appcmd list config -section:system.webServer/fastCgi | Select-String -SimpleMatch "fullPath=`"$($f.Python)`""
    if ($exists) {
        Run "`"$appcmd`" set config -section:system.webServer/fastCgi /-`"[fullPath='$($f.Python)',arguments='$($f.Wfastcgi)']`" /commit:apphost" | Out-Null
    }
}

function Write-WebConfig([string]$rel) {
    $f = Get-FastCgiArgs $rel
    $tpl = Get-Content (Join-Path $rel 'app\deploy\iis\web.config.template') -Raw
    $xml = $tpl.Replace('{{PYTHON}}', $f.Python).Replace('{{WFASTCGI}}', $f.Wfastcgi).
        Replace('{{APP_DIR}}', (Join-Path $rel 'app')).Replace('{{WEB_DIST}}', (Join-Path $rel 'web-dist')).
        Replace('{{ENV_FILE}}', $EnvFile).Replace('{{RELEASE}}', (Split-Path $rel -Leaf))
    $tmp = Join-Path $WwwRoot 'web.config.new'
    [IO.File]::WriteAllText($tmp, $xml, (New-Object Text.UTF8Encoding($false)))
    Move-Item $tmp (Join-Path $WwwRoot 'web.config') -Force   # IIS recycles the app on change
}

function Set-Worker([string]$rel) {
    $exe = Join-Path $rel 'venv\Scripts\dc-worker.exe'
    $logs = Join-Path $DataRoot 'logs'
    if (-not (Get-Service $WorkerService -ErrorAction SilentlyContinue)) {
        Run "`"$Nssm`" install $WorkerService `"$exe`"" | Out-Null
        Run "sc.exe config $WorkerService obj= `"$WorkerId`"" | Out-Null
        Run "`"$Nssm`" set $WorkerService DisplayName `"Data Collector - background job worker`"" | Out-Null
        Run "`"$Nssm`" set $WorkerService Start SERVICE_AUTO_START" | Out-Null
        Run "`"$Nssm`" set $WorkerService DependOnService DataCollectorGarnet MongoDB" | Out-Null
        Run "`"$Nssm`" set $WorkerService AppStdout `"$logs\worker.log`"" | Out-Null
        Run "`"$Nssm`" set $WorkerService AppStderr `"$logs\worker.log`"" | Out-Null
        Run "`"$Nssm`" set $WorkerService AppRotateFiles 1" | Out-Null
        Run "`"$Nssm`" set $WorkerService AppRotateOnline 1" | Out-Null
        Run "`"$Nssm`" set $WorkerService AppRotateBytes 10485760" | Out-Null
        Run "`"$Nssm`" set $WorkerService AppStopMethodConsole 30000" | Out-Null
        Run "`"$Nssm`" set $WorkerService AppExit Default Restart" | Out-Null
        Run "`"$Nssm`" set $WorkerService AppRestartDelay 5000" | Out-Null
    }
    Run "`"$Nssm`" set $WorkerService Application `"$exe`"" | Out-Null
    Run "`"$Nssm`" set $WorkerService AppDirectory `"$(Join-Path $rel 'app')`"" | Out-Null
    Run "`"$Nssm`" set $WorkerService AppEnvironmentExtra `"DC_ENV_FILE=$EnvFile`" `"PYTHONPATH=$(Join-Path $rel 'app')`" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1" | Out-Null
}

function Set-Acls {
    # Site + releases: read/execute only for the app pool and the worker.
    New-Item -ItemType Directory -Force $SiteRoot, $Releases, $WwwRoot | Out-Null
    Run "icacls `"$SiteRoot`" /inheritance:r /grant:r Administrators:(OI)(CI)F SYSTEM:(OI)(CI)F `"${PoolId}:(OI)(CI)RX`" `"${WorkerId}:(OI)(CI)RX`"" | Out-Null
    # Data root: admins only by default; scoped grants below.
    Run "icacls `"$DataRoot`" /inheritance:r /grant:r Administrators:(OI)(CI)F SYSTEM:(OI)(CI)F" | Out-Null
    foreach ($d in 'artifacts', 'logs') {
        $p = Join-Path $DataRoot $d; New-Item -ItemType Directory -Force $p | Out-Null
        Run "icacls `"$p`" /grant `"${PoolId}:(OI)(CI)M`" `"${WorkerId}:(OI)(CI)M`"" | Out-Null
    }
    $sec = Join-Path $DataRoot 'secrets'
    Run "icacls `"$sec`" /grant `"${PoolId}:RX`" `"${WorkerId}:RX`"" | Out-Null
    Run "icacls `"$EnvFile`" /grant `"${PoolId}:R`" `"${WorkerId}:R`"" | Out-Null
}

function Ensure-Site {
    if (-not (Test-Path "IIS:\AppPools\$SiteName")) {
        New-WebAppPool -Name $SiteName | Out-Null
    }
    $pool = "IIS:\AppPools\$SiteName"
    Set-ItemProperty $pool -Name managedRuntimeVersion -Value ''
    Set-ItemProperty $pool -Name managedPipelineMode -Value 'Integrated'
    Set-ItemProperty $pool -Name processModel.identityType -Value 'ApplicationPoolIdentity'
    Set-ItemProperty $pool -Name processModel.idleTimeout -Value ([TimeSpan]::Zero)
    Set-ItemProperty $pool -Name recycling.periodicRestart.time -Value ([TimeSpan]::Zero)
    Set-ItemProperty $pool -Name recycling.periodicRestart.privateMemory -Value 2097152   # KB
    Set-ItemProperty $pool -Name startMode -Value 'AlwaysRunning'

    if (-not (Get-Website -Name $SiteName)) {
        $clash = Get-WebBinding | Where-Object { $_.bindingInformation -like "*:80:$HostName" }
        if ($clash) { throw "Another site already binds ${HostName}:80" }
        New-Website -Name $SiteName -PhysicalPath $WwwRoot -ApplicationPool $SiteName -HostHeader $HostName -Port 80 | Out-Null
    }
    Set-ItemProperty "IIS:\Sites\$SiteName" -Name physicalPath -Value $WwwRoot
    # Anonymous requests run as the app pool identity (no IUSR file access needed).
    Run "`"$appcmd`" set config `"$SiteName`" -section:system.webServer/security/authentication/anonymousAuthentication /userName:`"`" /commit:apphost" | Out-Null
}

function Test-Release {
    $ok = $false
    for ($i = 0; $i -lt 20; $i++) {
        try {
            $r = Invoke-WebRequest -Uri 'http://127.0.0.1/health/ready' -Headers @{ Host = $HostName } -UseBasicParsing -TimeoutSec 30
            if ($r.StatusCode -eq 200) { $ok = $true; break }
        } catch { Start-Sleep -Seconds 3 }
    }
    if (-not $ok) { throw 'Health check /health/ready did not return 200' }
    Write-Host "   /health/ready: $($r.Content)"
}

function Activate([string]$rel) {
    Step "Activating $(Split-Path $rel -Leaf)"
    Register-FastCgi $rel
    Write-WebConfig $rel
    Set-Worker $rel
    Restart-WebAppPool -Name $SiteName -ErrorAction SilentlyContinue
    Restart-Service $WorkerService
    Test-Release
    Set-Content (Join-Path $SiteRoot 'CURRENT') (Split-Path $rel -Leaf) -Encoding ASCII
}

# ------------------------------------------------------------------------------------- main
Step 'Backing up IIS configuration'
$backup = "DataCollector-$(Get-Date -Format yyyyMMdd-HHmmss)"
Run "`"$appcmd`" add backup `"$backup`"" | Out-Null
Write-Host "   IIS backup: $backup  (restore: appcmd restore backup `"$backup`")"

if ($Rollback) {
    $current = (Get-Content (Join-Path $SiteRoot 'CURRENT') -ErrorAction Stop).Trim()
    $prev = Get-ChildItem $Releases -Directory | Sort-Object Name -Descending | Where-Object { $_.Name -lt $current } | Select-Object -First 1
    if (-not $prev) { throw "No release older than $current to roll back to" }
    Activate $prev.FullName
    Step "Rolled back from $current to $($prev.Name)"
    return
}

Set-Location -LiteralPath $RepoPath
$sha = (Run 'git rev-parse HEAD' | Select-Object -Last 1).Trim()
$dirty = Run 'git status --porcelain --untracked-files=no'
if ($dirty) { Write-Warning 'Working tree has uncommitted changes; the release contains them but is labelled with HEAD.' }
$relName = "$(Get-Date -Format yyyyMMdd-HHmmss)-$($sha.Substring(0,7))"
$rel = Join-Path $Releases $relName
Step "Building release $relName"
New-Item -ItemType Directory -Force $Releases | Out-Null
New-Item -ItemType Directory $rel | Out-Null

Step 'Admin UI: npm ci + build'
if (-not $SkipWebBuild) {
    Push-Location (Join-Path $RepoPath 'web')
    try { Run 'npm ci --no-audit --no-fund' | Out-Null; Run 'npm run build' | Out-Null } finally { Pop-Location }
}
cmd /c "robocopy `"$(Join-Path $RepoPath 'web\dist')`" `"$rel\web-dist`" /E /NFL /NDL /NJH /NJS /NP /XF *.map" | Out-Null
if ($LASTEXITCODE -ge 8) { throw 'copy of web-dist failed' }   # robocopy: 0-7 = success
if (-not (Test-Path "$rel\web-dist\index.html")) { throw 'web-dist has no index.html' }

Step 'Python code snapshot'
cmd /c "robocopy `"$RepoPath\data_collector`" `"$rel\app\data_collector`" /E /NFL /NDL /NJH /NJS /NP /XD __pycache__" | Out-Null
if ($LASTEXITCODE -ge 8) { throw 'copy of data_collector failed' }
New-Item -ItemType Directory -Force "$rel\app\deploy\iis" | Out-Null
Copy-Item "$RepoPath\deploy\__init__.py" "$rel\app\deploy\" ; Copy-Item "$RepoPath\deploy\iis\__init__.py", "$RepoPath\deploy\iis\wsgi.py", "$RepoPath\deploy\iis\web.config.template" "$rel\app\deploy\iis\"
@{ release = $relName; commit = $sha; built_at = (Get-Date).ToString('o'); dirty = [bool]$dirty } | ConvertTo-Json | Set-Content "$rel\RELEASE.json" -Encoding ASCII

Step 'Virtual environment'
Run "`"$BasePython`" -m venv `"$rel\venv`"" | Out-Null
Run "`"$rel\venv\Scripts\python.exe`" -m pip install -q --disable-pip-version-check --upgrade pip" | Out-Null
Run "`"$rel\venv\Scripts\python.exe`" -m pip install -q --disable-pip-version-check `"$RepoPath[iis]`"" | Out-Null
Run "`"$rel\venv\Scripts\python.exe`" -m pip check" | Out-Null
Run "`"$rel\venv\Scripts\python.exe`" -m compileall -q `"$rel\app`"" | Out-Null

Step 'Import check under the release interpreter'
$env:PYTHONPATH = "$rel\app"
Run "`"$rel\venv\Scripts\python.exe`" -c `"import deploy.iis, data_collector.hosting.iis_app, wfastcgi`"" | Out-Null
Remove-Item Env:PYTHONPATH

Step 'IIS site, app pool, ACLs'
Ensure-Site
if (-not (Get-Service $WorkerService -ErrorAction SilentlyContinue)) { Set-Worker $rel }   # account must exist before ACLs
Set-Acls

Activate $rel

Step 'Pruning old releases'
$keep = Get-ChildItem $Releases -Directory | Sort-Object Name -Descending | Select-Object -First $KeepReleases
Get-ChildItem $Releases -Directory | Where-Object { $keep.FullName -notcontains $_.FullName } | ForEach-Object {
    Unregister-FastCgi $_.FullName
    Remove-Item $_.FullName -Recurse -Force
    Write-Host "   removed $($_.Name)"
}
Step "Done: $relName is live"
