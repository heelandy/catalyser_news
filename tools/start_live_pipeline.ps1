# Starts the dashboard HTTP server and the live macro pipeline in the background.
# Safe to run repeatedly: it refuses to start a second runner or a second server.
param(
    [int]$DashboardPort = 8787,
    [int]$LoopSeconds = 60,
    [string]$StopAt = "18:00",
    [switch]$SkipDashboard
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

function Get-RunnerProcesses {
    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -like "python*" -and $_.CommandLine -match "macro_pipeline_runner\.py" }
}

function Get-DashboardProcesses {
    param([int]$Port)
    Get-CimInstance Win32_Process |
        Where-Object { $_.Name -like "python*" -and $_.CommandLine -match "http\.server $Port" }
}

$existingRunner = @(Get-RunnerProcesses)
if ($existingRunner.Count -gt 0) {
    Write-Output "Live runner already running (PID $($existingRunner[0].ProcessId)); not starting a duplicate."
} else {
    $runnerArgs = @(
        ".\macro_pipeline_runner.py",
        "--run-forever",
        "--watch-releases",
        "--loop-seconds", "$LoopSeconds"
    )
    if ($StopAt) {
        $runnerArgs += @("--stop-at", $StopAt)
    }
    $runner = Start-Process -FilePath "python" -ArgumentList $runnerArgs -WorkingDirectory $root -WindowStyle Hidden -PassThru
    Write-Output "Started live runner PID $($runner.Id) (stops daily at $StopAt)."
}

if (-not $SkipDashboard) {
    $existingDashboard = @(Get-DashboardProcesses -Port $DashboardPort)
    if ($existingDashboard.Count -gt 0) {
        Write-Output "Dashboard server already running (PID $($existingDashboard[0].ProcessId))."
    } else {
        $server = Start-Process -FilePath "python" -ArgumentList @("-m", "http.server", "$DashboardPort", "--bind", "127.0.0.1") -WorkingDirectory $root -WindowStyle Hidden -PassThru
        Write-Output "Started dashboard server PID $($server.Id) at http://127.0.0.1:$DashboardPort/dashboard/"
    }
}
