@echo off
chcp 65001 >nul
title CV Screener - server LAN
cd /d "%~dp0"

echo.
echo  Arresto di un'eventuale istanza precedente sulla porta 8000...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>nul
timeout /t 1 /nobreak >nul

set "LANIP="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1).IPAddress"`) do set "LANIP=%%i"

cd /d "%~dp0backend"
echo.
echo  CV Screener in ascolto su tutte le interfacce: 0.0.0.0:8000
echo  URL locale:       http://127.0.0.1:8000
if defined LANIP (echo  URL per il collega: http://%LANIP%:8000) else (echo  IP LAN non trovato: controlla la connessione di rete)
echo.
echo  Per fermare il server: chiudi questa finestra.
echo.
.venv\Scripts\python -m uvicorn main:app --host 0.0.0.0 --port 8000
echo.
echo  Server fermato.
pause
