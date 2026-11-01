@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Jalankan setup.bat lalu setup_grafik.bat terlebih dahulu.
  pause
  exit /b 1
)
set "SESSION=%~1"
if not defined SESSION set /p "SESSION=Folder sesi, contoh hasil\20261101-120000-abcdef: "
if not defined SESSION exit /b 1
".venv\Scripts\python.exe" -m wifi_lab.plots "%SESSION%"
set "result=%errorlevel%"
pause
exit /b %result%
