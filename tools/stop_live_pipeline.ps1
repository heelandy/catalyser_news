# Stops the live macro pipeline runner (and optionally the dashboard server).
param(
    [int]$DashboardPort = 8787,
    [switch]$IncludeDashboard
)

$ErrorActionPreference = "Stop"

$runners = @(Get-CimInstance Win32_Process |
    Where-Object { $_.Name -like "python*" -and $_.CommandLine -match "macro_pipeline_runner\.py" })
if ($runners.Count -eq 0) {
    Write-Output "No live runner process found."
} else {
    foreach ($proc in $runners) {
        Stop-Process -Id $proc.ProcessId -Force -Confirm:$false
        Write-Output "Stopped live runner PID $($proc.ProcessId)."
    }
}

if ($IncludeDashboard) {
    $servers = @(Get-CimInstance Win32_Process |
        Where-Object { $_.Name -like "python*" -and $_.CommandLine -match "http\.server $DashboardPort" })
    if ($servers.Count -eq 0) {
        Write-Output "No dashboard server process found on port $DashboardPort."
    } else {
        foreach ($proc in $servers) {
            Stop-Process -Id $proc.ProcessId -Force -Confirm:$false
            Write-Output "Stopped dashboard server PID $($proc.ProcessId)."
        }
    }
}
