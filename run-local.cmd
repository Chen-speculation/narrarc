@echo off
REM 绕过 PowerShell 执行策略，运行 run-local.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-local.ps1"
pause
