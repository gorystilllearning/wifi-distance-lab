@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Jalankan setup.bat terlebih dahulu.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m wifi_lab.controller %*
set "result=%errorlevel%"
if not "%result%"=="0" echo Program berhenti dengan kesalahan. Periksa pesan di atas.
pause
exit /b %result%
