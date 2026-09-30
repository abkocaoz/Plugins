@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (echo Once kurulum.bat calistirin. & pause & exit /b 1)
call .venv\Scripts\activate.bat
streamlit run app.py --server.headless false --browser.gatherUsageStats false --server.address localhost
pause
