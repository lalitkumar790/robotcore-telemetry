$ErrorActionPreference = "Stop"
Write-Host "Starting a temporary public Quick Tunnel to localhost:8765."
Write-Host "Keep the laptop bridge running in the other terminal. Stop this process after the field run."
cloudflared tunnel --url http://127.0.0.1:8765
