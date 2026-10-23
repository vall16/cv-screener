@echo off
chcp 65001 >nul
title CV Screener - setup locale (una tantum)
cd /d "%~dp0"

echo.
echo  === CV Screener - Setup locale (una tantum) ===
echo  Questo script si esegue UNA volta alla macchina.
echo  Poi per avviare il server: doppio click su start-server-admin.bat
echo.

REM --- 1. Prerequisiti ---
echo [1/4] Controllo prerequisiti...
where python >nul 2>nul
if errorlevel 1 (
    echo  [ERRORE] Python non trovato.
    echo          Installa Python 3.11+ da https://python.org
    echo          (durante l'installazione spunta "Add Python to PATH")
    pause
    exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
    echo  [ERRORE] Node.js non trovato.
    echo          Installa Node.js 20+ da https://nodejs.org
    pause
    exit /b 1
)
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    echo  OK: Python, Node.js e Chrome presenti.
) else (
    echo  [AVVISO] Chrome non trovato nel percorso standard.
    echo          Per il download da Indeed serve Google Chrome installato.
)
echo.

REM --- 2. Backend: venv + dipendenze ---
echo [2/4] Setup backend (venv + dipendenze)...
cd /d "%~dp0backend"
if not exist .venv (
    echo  Creo il virtual environment...
    python -m venv .venv
)
echo  Installo le dipendenze Python...
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 (
    echo  [ERRORE] Installazione dipendenze backend fallita.
    pause
    exit /b 1
)
echo  OK: backend pronto.
echo.

REM --- 3. Frontend: npm install + build ---
echo [3/4] Build frontend (npm install + build)...
cd /d "%~dp0frontend"
call npm install
if errorlevel 1 (
    echo  [ERRORE] npm install fallito.
    pause
    exit /b 1
)
call npm run build
if errorlevel 1 (
    echo  [ERRORE] npm run build fallito.
    pause
    exit /b 1
)
echo  OK: frontend buildato.
echo.

REM --- 4. Fine ---
echo [4/4] Setup completato!
echo.
echo  Per avviare il server:  doppio click su  start-server-admin.bat
echo  (la versione admin serve al download da Indeed: copia il profilo
echo   Chrome anche se e' aperto)
echo  URL: http://127.0.0.1:8000
echo.
pause
