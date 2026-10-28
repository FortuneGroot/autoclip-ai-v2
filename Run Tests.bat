@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Install AUTOCLIP AI first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto failed
echo.
echo Running the full local speech-to-clips sample...
".venv\Scripts\python.exe" tests\e2e_local.py
if errorlevel 1 goto failed
echo.
echo Running the iPhone server sample and download checks...
".venv\Scripts\python.exe" tests\e2e_mobile.py
if errorlevel 1 goto failed
echo.
echo All tests passed.
pause
exit /b 0
:failed
echo.
echo One or more tests failed. See the error above.
pause
exit /b 1
