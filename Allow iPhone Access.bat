@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Configure iPhone Firewall.ps1"
if errorlevel 1 (
  echo Firewall access was not enabled. The local setup page will explain what to do.
  pause
  exit /b 1
)
echo Done. You can now launch AUTOCLIP AI for iPhone.
pause
