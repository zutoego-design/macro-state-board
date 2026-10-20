@echo off
rem Double-click launcher. Everything real lives in run.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
pause
