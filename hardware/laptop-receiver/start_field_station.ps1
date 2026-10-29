$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Missing .venv\Scripts\python.exe. Create the laptop receiver venv and install requirements.txt first."
}

Write-Host ""
Write-Host "RobotCore local field station" -ForegroundColor Cyan
Write-Host "This detects the LoRa-E5 by USB ID and records only while a field session is active."
Write-Host "The phone must be able to reach one of the laptop IPs printed below and the Pi console."
Write-Host "If Windows Firewall blocks the phone, run setup_field_station_firewall.ps1 as Administrator."
Write-Host ""

& $Python bridge.py --host 0.0.0.0 --allow-lan-origins --managed-sessions --listen-port 8765

if ($LASTEXITCODE -ne 0) {
    Write-Host "Field station exited with code $LASTEXITCODE." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit $LASTEXITCODE
}
