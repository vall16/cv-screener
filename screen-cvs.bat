@echo off
chcp 65001 >nul
title CV Screener - opencode
cd /d "%~dp0"

where opencode >nul 2>nul
if errorlevel 1 (
  echo opencode non trovato. Installalo da https://opencode.ai, poi riprova.
  pause
  exit /b 1
)

set "CVFOLDER=%~dp0CVs"

echo ====================================
echo   CV SCREENER  (opencode / big-pickle)
echo ====================================
echo.
echo CV nella cartella: %CVFOLDER%
set /p ALTRA=(Invio per usarla, oppure scrivi un'altra cartella): 
if not "%ALTRA%"=="" set "CVFOLDER=%ALTRA%"

echo.
set /p PROFILO=Profilo target (es. senior backend developer): 
if "%PROFILO%"=="" set "PROFILO=profilo generico"

echo.
echo Lo screening e' in corso... puoi chiudere tutto e tornare dopo.
echo Il risultato finira' in: %CVFOLDER%\_report
echo.
opencode run --agent hr-recruiter "Analizza i CV in %CVFOLDER% per il profilo '%PROFILO%'. Scrivi i report e la classifica in _report" --auto

echo.
if exist "%CVFOLDER%\_report" (
  echo Fatto. Apro la cartella dei risultati...
  explorer "%CVFOLDER%\_report"
) else (
  echo Non ho trovato _report. Controlla l'output qui sopra.
)
pause