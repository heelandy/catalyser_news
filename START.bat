@echo off
rem Starts the NQ Catalyst dashboard and live pipeline in the background.
rem Safe to run any time: it skips anything that is already running.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_live_pipeline.ps1"
echo.
echo Dashboard: http://127.0.0.1:8787/dashboard/
pause
