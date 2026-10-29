# Run this script from an elevated PowerShell window.
$ErrorActionPreference = "Stop"
$ruleName = "RobotCore Local Field Station TCP 8765"
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Set-NetFirewallRule -DisplayName $ruleName -Enabled True -Profile Private -Action Allow
} else {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -Profile Private -Description "Allows the RobotCore phone field console to reach the authenticated laptop receiver on private networks only."
}
Write-Host "Private-profile inbound rule enabled for TCP 8765. Do not change this to the Public profile."
