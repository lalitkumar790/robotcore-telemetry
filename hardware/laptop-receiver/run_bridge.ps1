param(
    [Parameter(Mandatory=$true)][string]$Port,
    [Parameter(Mandatory=$true)][string]$ExperimentId
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (Test-Path ".venv\Scripts\python.exe") {
    & ".venv\Scripts\python.exe" bridge.py --port $Port --experiment-id $ExperimentId
} else {
    py bridge.py --port $Port --experiment-id $ExperimentId
}
