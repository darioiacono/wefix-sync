@echo off
echo ================================
echo   WeFix Sync - Setup e Avvio
echo ================================

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Python non trovato. Scaricalo da https://python.org
    pause
    exit /b 1
)

if not exist venv (
    echo Creazione ambiente virtuale...
    python -m venv venv
)

call venv\Scripts\activate.bat

echo Installazione dipendenze...
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo Installazione Playwright browser...
playwright install chromium

echo.
echo ================================
echo   Pronto! Apri: http://localhost:5000
echo ================================
echo.

python app.py
pause
