@echo off
setlocal
cd /d "%~dp0"
title AUTOCLIP AI Installation
echo Installing AUTOCLIP AI in this folder...
echo.
where py >nul 2>nul
if errorlevel 1 goto no_python
py -3.11 -c "import sys" >nul 2>nul
if not errorlevel 1 (
  set "PYTHON=py -3.11"
  goto make_venv
)
py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 (
  set "PYTHON=py -3.12"
  goto make_venv
)
echo Python 3.11 or 3.12 is required.
echo Download it from https://www.python.org/downloads/windows/ and run this installer again.
pause
exit /b 1
:no_python
echo The Windows Python launcher was not found.
echo Install Python 3.11 or 3.12 from https://www.python.org/downloads/windows/ and run this installer again.
pause
exit /b 1
:make_venv
if not exist ".venv\Scripts\python.exe" %PYTHON% -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import yt_dlp, imageio_ffmpeg, cv2; from pipeline import _windows_dll_directory; import os, sys; h=os.add_dll_directory(os.path.join(sys.prefix,'Scripts')); import faster_whisper; print('Dependencies verified'); print('FFmpeg:', imageio_ffmpeg.get_ffmpeg_exe())"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "from pipeline import ffmpeg_path; import subprocess; p=subprocess.run([ffmpeg_path(),'-hide_banner','-filters'],capture_output=True,text=True); q=subprocess.run([ffmpeg_path(),'-hide_banner','-encoders'],capture_output=True,text=True); assert p.returncode == 0 and ' ass ' in p.stdout, 'FFmpeg requires the libass caption filter'; assert q.returncode == 0 and 'libx264' in q.stdout, 'FFmpeg requires H.264 encoding'; print('FFmpeg filters and encoder verified')"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "from PIL import Image; from pathlib import Path; p=Path('mobile/icon.png'); Image.open(p).save('mobile/autoclip.ico', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128)])"
if errorlevel 1 goto failed
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Create Desktop Shortcut.ps1"
if errorlevel 1 (
  echo Desktop shortcut could not be created. You can still use Open AUTOCLIP AI.vbs in this folder.
) else (
  echo AUTOCLIP AI desktop shortcut is ready.
)
echo.
echo Installation finished.
pause
exit /b 0
:failed
echo.
echo Installation failed. Check the error above, then run this installer again.
pause
exit /b 1
