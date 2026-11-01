@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Jalankan setup.bat terlebih dahulu.
  pause
  exit /b 1
)
echo Memasang Matplotlib. Siapkan internet saat instalasi ini, bukan saat eksperimen.
".venv\Scripts\python.exe" -m pip install -r requirements-plot.txt
if errorlevel 1 goto gagal
".venv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto gagal
echo Grafik otomatis siap. Gunakan mulai.bat atau grafik.bat untuk CSV lama.
pause
exit /b 0
:gagal
echo Instalasi atau tes grafik gagal. Program pengukuran tanpa grafik tetap dapat digunakan.
pause
exit /b 1
