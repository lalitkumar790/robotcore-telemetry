$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Missing .venv\Scripts\python.exe. Create the laptop receiver venv and install requirements.txt first."
}

$keyDirectory = Join-Path $env:USERPROFILE ".robotcore"
$keyPath = Join-Path $keyDirectory "pairing.key"
if (-not (Test-Path $keyPath)) {
    New-Item -ItemType Directory -Force -Path $keyDirectory | Out-Null
    Write-Host ""
    Write-Host "One-time Pi/Laptop secure pairing setup" -ForegroundColor Cyan
    Write-Host "Paste the Base64 pairing key printed by install_field_console.sh on the Pi."
    Write-Host "This is a one-time transfer. Future runs pair automatically over LoRa."
    $pairingKey = Read-Host "Pi pairing key"
    try {
        $decoded = [Convert]::FromBase64String($pairingKey)
    } catch {
        throw "That value is not valid Base64. Copy the entire one-time pairing key from the Pi installer."
    }
    if ($decoded.Length -ne 32) {
        throw "Pairing key must decode to exactly 32 bytes. Do not use the Pi dashboard control token here."
    }
    [System.IO.File]::WriteAllText($keyPath, $pairingKey.Trim())
    try {
        icacls $keyPath /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
    } catch {
        Write-Warning "Could not tighten the pairing-key file ACL automatically. Keep $keyPath private."
    }
    Write-Host "Pairing key saved to $keyPath" -ForegroundColor Green
}
$env:ROBOTCORE_PAIRING_KEY_FILE = $keyPath

Write-Host ""
Write-Host "RobotCore local field station" -ForegroundColor Cyan
Write-Host "USB LoRa-E5 auto-detection is enabled. Receiver CSV is written only during a paired field session."
Write-Host "The Pi tunnel URL and short-lived control token will arrive in an AES-GCM encrypted LoRa beacon."
Write-Host "Open the local dashboard URL printed below on the laptop or a phone on the same private LAN."
Write-Host "No laptop Cloudflare tunnel or Pi SSH session is needed for each experiment."
Write-Host "If Windows Firewall blocks the phone, run setup_field_station_firewall.ps1 as Administrator."
Write-Host ""

& $Python bridge.py --host 0.0.0.0 --allow-lan-origins --managed-sessions --listen-port 8765 --pairing-key-file $keyPath

if ($LASTEXITCODE -ne 0) {
    Write-Host "Field station exited with code $LASTEXITCODE." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit $LASTEXITCODE
}
