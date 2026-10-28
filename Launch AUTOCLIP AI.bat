@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo AUTOCLIP AI is not installed yet.
  echo Double-click Install AUTOCLIP AI.bat first.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start Local AI.ps1"
start "AUTOCLIP AI" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
