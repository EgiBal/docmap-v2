# Stops the DocMap API (:8000) and UI (:3000), including their hidden parent processes.
$root = Split-Path -Parent $PSScriptRoot
$stopped = 0
foreach ($port in 8000, 3000) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue; $stopped++
    }
}
# Leftover launchers (uv / npm / node) that belong to this folder.
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$root*" -and $_.Name -match '^(uv|node|python|uvicorn)\.exe$' -and $_.ProcessId -ne $PID } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $stopped++ }
if ($stopped) { Write-Host '  DocMap is stopped.' -ForegroundColor Green } else { Write-Host '  DocMap was not running.' }
Start-Sleep -Seconds 2
