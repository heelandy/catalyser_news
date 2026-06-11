# Shows the live pipeline and dashboard process state plus the latest status files.
param(
    [int]$DashboardPort = 8787
)

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

$runners = @(Get-CimInstance Win32_Process |
    Where-Object { $_.Name -like "python*" -and $_.CommandLine -match "macro_pipeline_runner\.py" })
if ($runners.Count -gt 0) {
    foreach ($proc in $runners) {
        Write-Output "Live runner RUNNING: PID $($proc.ProcessId)"
    }
} else {
    Write-Output "Live runner NOT RUNNING."
}

$servers = @(Get-CimInstance Win32_Process |
    Where-Object { $_.Name -like "python*" -and $_.CommandLine -match "http\.server $DashboardPort" })
if ($servers.Count -gt 0) {
    Write-Output "Dashboard server RUNNING: PID $($servers[0].ProcessId) at http://127.0.0.1:$DashboardPort/dashboard/"
} else {
    Write-Output "Dashboard server NOT RUNNING on port $DashboardPort."
}

$statusPath = Join-Path $root "macro_pipeline_status.json"
if (Test-Path $statusPath) {
    Write-Output ""
    Write-Output "--- macro_pipeline_status.json ---"
    Get-Content $statusPath
}

$logPath = Join-Path $root "macro_pipeline_runner.log"
if (Test-Path $logPath) {
    Write-Output ""
    Write-Output "--- macro_pipeline_runner.log (last 15 lines) ---"
    Get-Content $logPath -Tail 15
}
