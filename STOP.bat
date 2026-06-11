@echo off
rem Stops the NQ Catalyst live pipeline runner.
rem The dashboard web server stays running so you can keep viewing the last data.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\stop_live_pipeline.ps1"
echo.
echo The dashboard stays up at http://127.0.0.1:8787/dashboard/
echo To stop the dashboard too, run:
echo   powershell -NoProfile -ExecutionPolicy Bypass -File tools\stop_live_pipeline.ps1 -IncludeDashboard
pause
