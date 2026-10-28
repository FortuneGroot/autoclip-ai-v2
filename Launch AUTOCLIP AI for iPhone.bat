@echo off
setlocal
cd /d "%~dp0"
title AUTOCLIP AI for iPhone
if not exist ".venv\Scripts\python.exe" (
  echo AUTOCLIP AI is not installed yet.
  echo Double-click Install AUTOCLIP AI.bat first.
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Configure iPhone Firewall.ps1"
if errorlevel 1 echo Windows Firewall access was not enabled. The iPhone may be unable to connect.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start iPhone Server.ps1"
if errorlevel 1 (
  echo.
  echo Could not start the iPhone app. Check the error above.
  pause
)
