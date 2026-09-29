@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Gereksinim Karsilastirma - Kurulum ===
where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)
%PY% --version || (echo Python bulunamadi. https://www.python.org adresinden Python 3.10+ kurun. & pause & exit /b 1)
if not exist .venv %PY% -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (echo Kurulum basarisiz. Kurumsal proxy varsa pip icin proxy ayarlayin. & pause & exit /b 1)
echo.
echo Kurulum tamamlandi. Uygulamayi baslatmak icin baslat.bat dosyasini calistirin.
pause
