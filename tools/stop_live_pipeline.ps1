# Stops the live macro pipeline runner and the tape signal listener
# (and optionally the dashboard server).
param(
    [int]$DashboardPort = 8787,
    [switch]$IncludeDashboard
)

$ErrorActionPreference = "Stop"

$pyProcs = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -like "python*" })

$runners = @($pyProcs | Where-Object { $_.CommandLine -match "macro_pipeline_runner\.py" })
if ($runners.Count -eq 0) {
    Write-Output "No live runner process found."
} else {
    foreach ($proc in $runners) {
        Stop-Process -Id $proc.ProcessId -Force -Confirm:$false
        Write-Output "Stopped live runner PID $($proc.ProcessId)."
    }
}

$listeners = @($pyProcs | Where-Object { $_.CommandLine -match "tape_signal_listener\.py" })
if ($listeners.Count -eq 0) {
    Write-Output "No tape signal listener process found."
} else {
    foreach ($proc in $listeners) {
        Stop-Process -Id $proc.ProcessId -Force -Confirm:$false
        Write-Output "Stopped tape signal listener PID $($proc.ProcessId)."
    }
}

if ($IncludeDashboard) {
    $servers = @($pyProcs | Where-Object {
        $_.CommandLine -match "http\.server $DashboardPort" -or
        ($_.CommandLine -match "dashboard_server\.py" -and $_.CommandLine -match "--port $DashboardPort")
    })
    if ($servers.Count -eq 0) {
        Write-Output "No dashboard server process found on port $DashboardPort."
    } else {
        foreach ($proc in $servers) {
            Stop-Process -Id $proc.ProcessId -Force -Confirm:$false
            Write-Output "Stopped dashboard server PID $($proc.ProcessId)."
        }
    }
}
