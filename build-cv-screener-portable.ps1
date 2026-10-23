#requires -Version 5.1
<#
    Costruisce il pacchetto portable COMPLETO di CV Screener per un PC Windows:
    backend, frontend gia' compilato, runtime Python, opencode e downloader Indeed.

    Contenuto prodotto in dist\:
      - cv-screener-portable\      (cartella pronta da usare)
      - cv-screener-portable.zip   (da consegnare all'utente)

    Uso:
      powershell -NoProfile -ExecutionPolicy Bypass -File .\build-cv-screener-portable.ps1

    Opzioni:
      -SkipFrontend        non ricompila il frontend (usa frontend\dist esistente)
      -OpencodeExe <path>  percorso di opencode.exe (default: installazione npm globale)
#>
[CmdletBinding()]
param(
    [string]$PythonVersion = "3.11.9",
    [string]$OutDir = "",
    [string]$OpencodeExe = "",
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoRoot = $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $RepoRoot "dist" }
$Name = "cv-screener-portable"
$Staging = Join-Path $OutDir $Name
$ZipPath = Join-Path $OutDir "$Name.zip"
$EmbedZip = Join-Path $OutDir "python-embed.zip"
$EmbedUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"

$parts = $PythonVersion -split '\.'
$pyTag = $parts[0..1] -join '.'
$pyShort = $parts[0..1] -join ''
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$utf8Bom = New-Object System.Text.UTF8Encoding($true)

function Write-TextFile {
    param([string]$Path, [string]$Text, [switch]$Bom)
    $Text = $Text -replace "`r`n", "`n" -replace "`n", "`r`n"
    $enc = if ($Bom) { $utf8Bom } else { $utf8NoBom }
    [IO.File]::WriteAllText($Path, $Text, $enc)
}

Write-Host "==> Build $Name (Python $PythonVersion)"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "py launcher non trovato. Installa Python $pyTag e riprova."
}

if (-not $OpencodeExe) {
    $candidates = @(
        (Join-Path $env:APPDATA "npm\node_modules\opencode-ai\bin\opencode.exe"),
        (Join-Path $env:LOCALAPPDATA "opencode\bin\opencode.exe")
    )
    $OpencodeExe = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}
if (-not $OpencodeExe -or -not (Test-Path $OpencodeExe)) {
    throw "opencode.exe non trovato. Installalo (npm i -g opencode-ai) oppure passa -OpencodeExe <percorso>."
}

if (-not $SkipFrontend) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm non trovato. Serve Node.js per compilare il frontend (o usa -SkipFrontend)."
    }
    Write-Host "==> Build frontend (Angular)"
    Push-Location (Join-Path $RepoRoot "frontend")
    try {
        if (-not (Test-Path "node_modules")) {
            & npm install --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw "npm install fallito (exit $LASTEXITCODE)" }
        }
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build fallito (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
}
$FrontendDist = Join-Path $RepoRoot "frontend\dist\cv-screener\browser"
if (-not (Test-Path (Join-Path $FrontendDist "index.html"))) {
    throw "Frontend non compilato: manca $FrontendDist\index.html"
}

if (Test-Path $Staging) { Remove-Item -Recurse -Force $Staging }
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Staging "python") | Out-Null

Write-Host "==> Runtime: Python $PythonVersion embeddable"
if (-not (Test-Path $EmbedZip)) {
    Invoke-WebRequest -Uri $EmbedUrl -OutFile $EmbedZip -UseBasicParsing
}
Expand-Archive -Path $EmbedZip -DestinationPath (Join-Path $Staging "python") -Force

$pthPath = Join-Path $Staging "python\python$pyShort._pth"
if (-not (Test-Path $pthPath)) { throw "_pth non trovato: $pthPath" }
$pthContent = @(
    "python$pyShort.zip",
    ".",
    "Lib\site-packages",
    "import site"
) -join "`r`n"
[IO.File]::WriteAllText($pthPath, $pthContent, $utf8NoBom)

Write-Host "==> Dipendenze backend + downloader nel runtime"
$sitePkgs = Join-Path $Staging "python\Lib\site-packages"
New-Item -ItemType Directory -Force -Path $sitePkgs | Out-Null
$requirements = @(
    (Join-Path $RepoRoot "backend\requirements.txt"),
    (Join-Path $RepoRoot "indeed-downloader\requirements.txt")
)
foreach ($req in $requirements) {
    & py "-$pyTag" -m pip install --disable-pip-version-check --ignore-installed `
        --no-warn-script-location --target "$sitePkgs" -r "$req"
    if ($LASTEXITCODE -ne 0) { throw "pip install fallito per $req (exit $LASTEXITCODE)" }
}

Write-Host "==> Verifica che il runtime importi le dipendenze"
& (Join-Path $Staging "python\python.exe") -c "import fastapi, uvicorn, markdown, docx, xhtml2pdf, selenium, tqdm, dotenv, chromedriver_autoinstaller; print('deps OK')"
if ($LASTEXITCODE -ne 0) { throw "Il runtime embeddable non riesce a importare le dipendenze" }

Write-Host "==> Backend"
$BackendDst = Join-Path $Staging "backend"
New-Item -ItemType Directory -Force -Path $BackendDst | Out-Null
foreach ($f in @("main.py", "screener.py", "indeed_runner.py", "requirements.txt")) {
    Copy-Item (Join-Path $RepoRoot "backend\$f") $BackendDst
}

Write-Host "==> Frontend compilato"
$FeDst = Join-Path $Staging "frontend\dist\cv-screener"
New-Item -ItemType Directory -Force -Path $FeDst | Out-Null
Copy-Item $FrontendDist (Join-Path $FeDst "browser") -Recurse

Write-Host "==> Agente opencode"
New-Item -ItemType Directory -Force -Path (Join-Path $Staging ".opencode") | Out-Null
Copy-Item (Join-Path $RepoRoot ".opencode\agent") (Join-Path $Staging ".opencode\agent") -Recurse
Copy-Item (Join-Path $RepoRoot ".opencode\command") (Join-Path $Staging ".opencode\command") -Recurse
Copy-Item (Join-Path $RepoRoot "opencode.json") $Staging

Write-Host "==> Downloader Indeed"
$IndeedDst = Join-Path $Staging "indeed-downloader"
New-Item -ItemType Directory -Force -Path $IndeedDst | Out-Null
foreach ($f in @("indeed_downloader.py", "requirements.txt", "upload_to_server.py", "LICENSE")) {
    Copy-Item (Join-Path $RepoRoot "indeed-downloader\$f") $IndeedDst
}
Copy-Item (Join-Path $RepoRoot "indeed-downloader\.env.example") (Join-Path $IndeedDst ".env.config")
New-Item -ItemType Directory -Force -Path (Join-Path $IndeedDst "downloads") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $IndeedDst "logs") | Out-Null

Write-Host "==> Dati e opencode"
New-Item -ItemType Directory -Force -Path (Join-Path $Staging "CVs\_report") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Staging "bin") | Out-Null
Copy-Item $OpencodeExe (Join-Path $Staging "bin\opencode.exe")

$launcher = @'
@echo off
chcp 65001 >nul
title CV Screener
cd /d "%~dp0"
setlocal

set "PATH=%~dp0bin;%~dp0python;%~dp0python\Scripts;%PATH%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

echo.
echo  ============================================================
echo   CV Screener - versione portable
echo  ============================================================
echo.

if not exist "%~dp0python\python.exe" (
    echo  [ERRORE] Installazione incompleta: manca la cartella "python".
    echo          Estrai di nuovo lo zip completo.
    pause
    exit /b 1
)
if not exist "%~dp0frontend\dist\cv-screener\browser\index.html" (
    echo  [ERRORE] Installazione incompleta: manca il frontend compilato.
    echo          Estrai di nuovo lo zip completo.
    pause
    exit /b 1
)

powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>nul

echo  Avvio su http://127.0.0.1:8000
echo  Chiudi questa finestra per fermare CV Screener.
echo.

start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process explorer.exe -ArgumentList 'http://127.0.0.1:8000'"

cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
set "RC=%ERRORLEVEL%"

echo.
echo  Server fermato ^(codice %RC%^).
pause
endlocal
'@
Write-TextFile (Join-Path $Staging "AVVIA-CV-SCREENER.cmd") $launcher

$adminLauncher = @'
@echo off
chcp 65001 >nul
title CV Screener (amministratore)
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
    echo  Richiesta privilegi di amministratore... conferma nella finestra di Windows.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

call "%~dp0AVVIA-CV-SCREENER.cmd"
'@
Write-TextFile (Join-Path $Staging "AVVIA-CV-SCREENER-ADMIN.cmd") $adminLauncher

$readme = @'
CV SCREENER - VERSIONE PORTABLE (WINDOWS)
=========================================

Non serve installare Python, Node.js o altri programmi: e' tutto in questa
cartella. Servono solo Google Chrome e un account opencode.

INSTALLAZIONE
-------------
1. Estrai lo zip in una cartella scrivibile, ad esempio Documenti o Desktop.
   Non usare C:\Program Files (non e' scrivibile senza amministratore).
2. Doppio click su AVVIA-CV-SCREENER.cmd
3. Il browser si apre su http://127.0.0.1:8000

USO
---
1. Nella web UI trascina i CV (PDF/TXT) nell'area CV, oppure usa
   "Scarica da Indeed" (vedi sotto).
2. Scrivi il profilo target e avvia lo screening.
3. I report restano in CVs\_report e sono visibili nella web UI.

SCARICARE I CV DA INDEED
------------------------
Il downloader Indeed e' incluso. Funziona dal pannello "Scarica da Indeed"
della web UI, ma serve:
- Google Chrome installato e con accesso a Indeed Employer;
- idealmente Chrome chiuso durante l'aggiornamento della sessione.

Se Chrome e' aperto e la copia del profilo fallisce, avvia il programma con
AVVIA-CV-SCREENER-ADMIN.cmd (chiede i privilegi di amministratore).

Nel pannello, se compare un menu nel log, scegli: 1 - 1 - 2 - 4
(English, Backend API, All jobs, Active+Paused). Se chiede il login,
accedi nella finestra di Chrome e premi Invio.

Al termine usa "Sincronizza CV" nella web UI per importare i PDF scaricati.

DATI E BACKUP
-------------
- CV caricati:            CVs\
- Report dello screening: CVs\_report\
- Storico job/sessioni:   backend\jobs.json, backend\sessions.json,
                          backend\profiles.json, backend\shortlist.json
- CV scaricati da Indeed: indeed-downloader\downloads\

Per un backup copia queste cartelle/file. Per fermare il programma chiudi
la finestra nera.

PROBLEMI COMUNI
---------------
- "Porta 8000 occupata": il launcher chiude l'istanza precedente.
- Antivirus che blocca python.exe/opencode.exe: aggiungi la cartella alle
  esclusioni.
- Chrome non trovato: installa Chrome e accedi a Indeed almeno una volta.
- Se lo screening si ferma con un errore di autenticazione o di modello,
  apri una finestra nella cartella del programma e lancia:
      bin\opencode.exe auth login
  (oppure configura un provider e una API key in opencode.json).
- Modello AI: e' impostato in opencode.json (opencode/big-pickle). Puoi
  cambiarlo con un provider e una API key a tua scelta.

PRIVACY
-------
I CV restano su questo PC e vengono inviati solo a opencode per l'analisi.
Non condividere questa cartella: contiene i dati dei candidati.
'@
Write-TextFile (Join-Path $Staging "LEGGIMI.txt") $readme -Bom

Write-Host "==> Comprimo in $ZipPath"
$tar = Get-Command tar.exe -ErrorAction SilentlyContinue
if ($tar) {
    & tar.exe -a -cf $ZipPath -C $OutDir $Name
    if ($LASTEXITCODE -ne 0) { throw "tar ha fallito (exit $LASTEXITCODE)" }
} else {
    Compress-Archive -Path $Staging -DestinationPath $ZipPath -CompressionLevel Optimal -Force
}

if (Test-Path $EmbedZip) { Remove-Item -Force $EmbedZip }

$sizeMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 1)
Write-Host ""
Write-Host "Fatto."
Write-Host "  Cartella: $Staging"
Write-Host "  Zip:      $ZipPath  ($sizeMb MB)"
