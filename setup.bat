@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ diperlukan'"
if errorlevel 1 goto gagal
py -3 -m venv .venv
if errorlevel 1 goto gagal
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto gagal
echo.
echo Siap. Aktifkan hotspot 2.4 GHz lalu jalankan mulai.bat.
echo Tidak ada paket pip yang perlu diunduh.
echo Grafik PNG opsional: jalankan setup_grafik.bat sebelum eksperimen saat internet tersedia.
pause
exit /b 0
:gagal
echo Setup gagal. Pasang Python 3.11+ beserta Python Launcher lalu coba lagi.
pause
exit /b 1
