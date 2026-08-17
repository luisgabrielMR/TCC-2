@echo off
setlocal
cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0powershell\rodar-linguagem.ps1" -Language python -Scenario mixed -RunNumber 0 -LoadProfile controlled_50
pause
