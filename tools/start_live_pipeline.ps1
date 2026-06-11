# Starts the dashboard HTTP server and the live macro pipeline in the background.
# Safe to run repeatedly: it refuses to start a second runner or a second server.
# The dashboard always starts; the runner only starts inside the StartAt-StopAt
# window unless -ForceRunner is passed.
param(
    [int]$DashboardPort = 8787,
    [int]$LoopSeconds = 60,
    [string]$StartAt = "07:00",
    [string]$StopAt = "18:00",
    [switch]$SkipDashboard,
    [switch]$ForceRunner
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

function In-ActiveWindow {
    param([string]$Start, [string]$Stop)
    try {
        $now = (Get-Date).TimeOfDay
        $startTime = [TimeSpan]::Parse($Start)
        $stopTime = [TimeSpan]::Parse($Stop)
        return ($now -ge $startTime) -and ($now -lt $stopTime)
    } catch {
        return $true
    }
}

$existingRunner = @(Get-RunnerProcesses)
if ($existingRunner.Count -gt 0) {
    Write-Output "Live runner already running (PID $($existingRunner[0].ProcessId)); not starting a duplicate."
} elseif (-not $ForceRunner -and -not (In-ActiveWindow -Start $StartAt -Stop $StopAt)) {
    Write-Output "Outside the $StartAt-$StopAt window; runner not started (it starts at $StartAt, or pass -ForceRunner to start now)."
} else {
    $runnerArgs = @(
        ".\macro_pipeline_runner.py",
        "--run-forever",
        "--watch-releases",
        "--refresh-performance",
        "--refresh-probability-validation",
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
