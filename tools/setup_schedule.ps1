# Registers Windows Task Scheduler tasks so the live pipeline starts at 7:00 AM,
# stops at 6:00 PM, and repeats every day. Run with -Remove to unregister.
param(
    [string]$StartTime = "07:00",
    [string]$StopTime = "18:00",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$startScript = Join-Path $root "tools\start_live_pipeline.ps1"
$stopScript = Join-Path $root "tools\stop_live_pipeline.ps1"
$startTaskName = "NQ Catalyst Pipeline Start"
$stopTaskName = "NQ Catalyst Pipeline Stop"

if ($Remove) {
    foreach ($name in @($startTaskName, $stopTaskName)) {
        try {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction Stop
            Write-Output "Removed scheduled task: $name"
        } catch {
            Write-Output "Scheduled task not found: $name"
        }
    }
    return
}

$psExe = "powershell.exe"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

$startAction = New-ScheduledTaskAction -Execute $psExe `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`" -StartAt $StartTime -StopAt $StopTime" `
    -WorkingDirectory $root
$startTriggers = @(
    (New-ScheduledTaskTrigger -Daily -At $StartTime),
    (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME")
)
Register-ScheduledTask -TaskName $startTaskName -Action $startAction -Trigger $startTriggers -Settings $settings -Force | Out-Null
Write-Output "Registered: $startTaskName (daily at $StartTime, and at every logon so the dashboard survives reboots)"

$stopAction = New-ScheduledTaskAction -Execute $psExe `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$stopScript`"" `
    -WorkingDirectory $root
$stopTrigger = New-ScheduledTaskTrigger -Daily -At $StopTime
Register-ScheduledTask -TaskName $stopTaskName -Action $stopAction -Trigger $stopTrigger -Settings $settings -Force | Out-Null
Write-Output "Registered: $stopTaskName (daily at $StopTime)"

Write-Output ""
Write-Output "The runner also exits on its own at $StopTime via --stop-at, so the stop task is a backstop."
Write-Output "The dashboard server stays running so you can keep viewing the last data; use tools\stop_live_pipeline.ps1 -IncludeDashboard to stop it too."
