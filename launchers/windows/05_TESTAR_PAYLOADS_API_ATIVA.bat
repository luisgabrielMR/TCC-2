@echo off
setlocal
cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0powershell\testar-payloads.ps1" -BaseUrl "http://127.0.0.1:8000"
pause
