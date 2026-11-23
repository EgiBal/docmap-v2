# Starts DocMap in the background (no extra windows) and opens the browser.
# Called by "Start DocMap.bat". Logs: data\logs\api.log, ui.log (+ .err.log).
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$logs = Join-Path $root 'data\logs'
New-Item -ItemType Directory -Force $logs | Out-Null
$ui = 'http://localhost:3000'

function Test-Port($port) { [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) }

Write-Host ''
Write-Host '  DocMap' -ForegroundColor Cyan
Write-Host '  ------'

if (-not (Test-Path "$root\backend\.env")) {
    Copy-Item "$root\backend\.env.example" "$root\backend\.env"
    Write-Host '  Created backend\.env. Add your NVIDIA key in the app (Settings), or use a local model.' -ForegroundColor Yellow
}
foreach ($tool in 'uv', 'npm') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Host "  '$tool' is not installed. See README.md > Requirements." -ForegroundColor Red
        Read-Host '  Press Enter to close'; exit 1
    }
}

if ((Test-Port 8000) -and (Test-Port 3000)) {
    Write-Host '  DocMap is already running. Opening the browser.'
    Start-Process $ui; Start-Sleep 2; exit 0
}
if ((Test-Port 8000) -or (Test-Port 3000)) {
    Write-Host '  Port 8000 or 3000 is used by another program (maybe an old DocMap). Run "Stop DocMap.bat" first.' -ForegroundColor Red
    Read-Host '  Press Enter to close'; exit 1
}

# 1. API (Python). First start installs the packages into backend\.venv.
Write-Host '  Starting the API ...'
Start-Process -FilePath 'uv' -ArgumentList 'run', 'uvicorn', 'docmap.api:app', '--host', '127.0.0.1', '--port', '8000' `
    -WorkingDirectory "$root\backend" -WindowStyle Hidden `
    -RedirectStandardOutput "$logs\api.log" -RedirectStandardError "$logs\api.err.log"

# 2. UI (Next.js production build). Rebuild only when the source is newer than the last build.
$fe = "$root\frontend"
if (-not (Test-Path "$fe\node_modules")) {
    Write-Host '  First start: installing the UI packages (1-3 minutes) ...'
    Push-Location $fe; npm install --no-audit --no-fund | Out-File "$logs\npm-install.log"; Pop-Location
}
$buildId = "$fe\.next\BUILD_ID"
$newest = Get-ChildItem "$fe\app", "$fe\components", "$fe\lib" -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not (Test-Path $buildId) -or $newest.LastWriteTime -gt (Get-Item $buildId).LastWriteTime) {
    Write-Host '  Building the UI (about 1 minute, only after changes) ...'
    Push-Location $fe
    & npm.cmd run build *> "$logs\ui-build.log"
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) {
        Write-Host "  The UI build failed. See $logs\ui-build.log" -ForegroundColor Red
        Read-Host '  Press Enter to close'; exit 1
    }
}
Write-Host '  Starting the UI ...'
Start-Process -FilePath 'npm.cmd' -ArgumentList 'run', 'start' -WorkingDirectory $fe -WindowStyle Hidden `
    -RedirectStandardOutput "$logs\ui.log" -RedirectStandardError "$logs\ui.err.log"

# 3. Wait for both, then open the browser.
$ok = $false
for ($i = 0; $i -lt 120; $i++) {
    if ((Test-Port 8000) -and (Test-Port 3000)) { $ok = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $ok) {
    Write-Host "  DocMap did not start in 2 minutes. See the logs in $logs" -ForegroundColor Red
    Read-Host '  Press Enter to close'; exit 1
}
Start-Process $ui
Write-Host ''
Write-Host "  DocMap runs in the background at $ui" -ForegroundColor Green
Write-Host '  You can close this window. To stop DocMap, double-click "Stop DocMap.bat".'
Start-Sleep -Seconds 4
