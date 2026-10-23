#requires -Version 5.1
<#
    Costruisce un pacchetto portable del downloader Indeed per un PC Windows
    senza Python installato.

    Contenuto prodotto in dist\:
      - indeed-downloader-portable\      (cartella pronta da usare)
      - indeed-downloader-portable.zip   (da consegnare all'utente)

    Uso:
      powershell -NoProfile -ExecutionPolicy Bypass -File .\build-indeed-portable.ps1
#>
[CmdletBinding()]
param(
    [string]$PythonVersion = "3.11.9",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$RepoRoot = $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $RepoRoot "dist" }
$Name = "indeed-downloader-portable"
$Staging = Join-Path $OutDir $Name
$ZipPath = Join-Path $OutDir "$Name.zip"
$EmbedZip = Join-Path $OutDir "python-embed.zip"
$EmbedUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"

$parts = $PythonVersion -split '\.'
$pyTag = $parts[0..1] -join '.'          # 3.11
$pyShort = $parts[0..1] -join ''         # 311
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$utf8Bom = New-Object System.Text.UTF8Encoding($true)

Write-Host "==> Build $Name (Python $PythonVersion)"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "py launcher non trovato. Installa Python $pyTag e riprova."
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
if (-not (Test-Path $pthPath)) {
    throw "_pth non trovato: $pthPath"
}
$pthContent = @(
    "python$pyShort.zip",
    ".",
    "Lib\site-packages",
    "import site"
) -join "`r`n"
[IO.File]::WriteAllText($pthPath, $pthContent, $utf8NoBom)

Write-Host "==> Dipendenze del downloader nel runtime"
$sitePkgs = Join-Path $Staging "python\Lib\site-packages"
New-Item -ItemType Directory -Force -Path $sitePkgs | Out-Null
$requirements = Join-Path $RepoRoot "indeed-downloader\requirements.txt"
& py "-$pyTag" -m pip install --disable-pip-version-check --ignore-installed `
    --no-warn-script-location --target "$sitePkgs" -r "$requirements"
if ($LASTEXITCODE -ne 0) { throw "pip install fallito (exit $LASTEXITCODE)" }

Write-Host "==> Verifica che il runtime importi le dipendenze"
& (Join-Path $Staging "python\python.exe") -c "import selenium, tqdm, dotenv, chromedriver_autoinstaller; print('deps OK')"
if ($LASTEXITCODE -ne 0) { throw "Il runtime embeddable non riesce a importare le dipendenze" }

Write-Host "==> File dell'applicazione"
Copy-Item (Join-Path $RepoRoot "indeed-downloader\indeed_downloader.py") $Staging
Copy-Item (Join-Path $RepoRoot "indeed-downloader\upload_to_server.py") $Staging
Copy-Item (Join-Path $RepoRoot "indeed-downloader\requirements.txt") $Staging
Copy-Item (Join-Path $RepoRoot "backend\indeed_runner.py") $Staging
Copy-Item (Join-Path $RepoRoot "indeed-downloader\.env.example") (Join-Path $Staging ".env.config")
New-Item -ItemType Directory -Force -Path (Join-Path $Staging "downloads") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Staging "logs") | Out-Null

$launcher = @'
@echo off
chcp 65001 >nul
title Indeed CV Downloader - portable
cd /d "%~dp0"
setlocal

set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "PYTHONUTF8=1"

echo.
echo  ============================================================
echo   Indeed CV Downloader - versione portable
echo  ============================================================
echo.
echo  Requisiti: Google Chrome installato e con accesso a Indeed.
echo.

set "CHROME_USER_DATA=%LOCALAPPDATA%\Google\Chrome\User Data"
if not exist "%CHROME_USER_DATA%\Local State" (
    echo  [ERRORE] Profilo Google Chrome non trovato in:
    echo           %CHROME_USER_DATA%
    echo.
    echo  Installa Google Chrome e accedi a Indeed almeno una volta.
    echo.
    pause
    exit /b 1
)

echo  CHIUDI tutte le finestre di Chrome, poi premi un tasto.
echo  ^(serve per copiare la sessione Indeed senza rifare il login^)
pause >nul

echo.
echo  Copio la sessione dal profilo Chrome...
set "CHROME_COPY_PROFILE=%~dp0chrome-profile-copy"
if not exist "%CHROME_COPY_PROFILE%" mkdir "%CHROME_COPY_PROFILE%"
robocopy "%CHROME_USER_DATA%" "%CHROME_COPY_PROFILE%" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /XD Cache "Code Cache" GPUCache GrShaderCache "Service Worker" CachedData >nul
if errorlevel 8 echo  [AVVISO] Alcuni file non copiati. Uso la copia precedente.
cmd /c exit 0

echo.
echo  Nel menu scegli:  1 - 1 - 2 - 4
echo  Se chiede il login, accedi a Indeed nella finestra di Chrome
echo  che si apre e poi premi Invio qui.
echo.
python\python.exe indeed_runner.py indeed_downloader.py
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo  Downloader chiuso con errore ^(codice %RC%^). Guarda i messaggi sopra.
) else (
    echo  Fatto. I PDF sono in: %~dp0downloads
    echo  Ora caricali nella web UI di CV Screener ^(area CV^).
)
echo.
pause
endlocal
'@
[IO.File]::WriteAllText((Join-Path $Staging "AVVIA-DOWNLOADER.cmd"), $launcher, $utf8NoBom)

$uploader = @'
@echo off
chcp 65001 >nul
title Carica CV su CV Screener
cd /d "%~dp0"
setlocal

set "PYTHONUTF8=1"

echo.
echo  ============================================================
echo   Carica i CV sul server CV Screener
echo  ============================================================
echo.
echo  Prende i PDF da questa cartella (downloads) e li invia
echo  alla web UI di CV Screener nella LAN.
echo.

set "SERVER="
set /p "SERVER=URL del server (es. http://192.168.1.10:8000): "
if "%SERVER%"=="" (
    echo  Nessun URL inserito.
    pause
    exit /b 1
)

echo.
python\python.exe upload_to_server.py "%SERVER%"
echo.
pause
endlocal
'@
[IO.File]::WriteAllText((Join-Path $Staging "CARICA-SU-SERVER.cmd"), $uploader, $utf8NoBom)

$readme = @'
INDEED CV DOWNLOADER - VERSIONE PORTABLE
========================================

Non serve installare Python: e' tutto dentro questa cartella.
Serve solo Google Chrome installato e un account Indeed Employer.

PRIMA DI INIZIARE
-----------------
1. Apri Chrome e verifica di essere loggato su https://employers.indeed.com
2. Chiudi TUTTE le finestre di Chrome.
3. Doppio click su AVVIA-DOWNLOADER.cmd

NEL MENU
--------
Scegli, in quest'ordine:
  1  = English (o 2 = Francais)
  1  = Backend (API)
  2  = All jobs
  4  = Active + Paused

Se il downloader chiede di fare login, accedi nella finestra di Chrome che
si apre e poi premi Invio nella finestra nera.

DOVE FINISCONO I PDF
--------------------
Nella cartella "downloads" (sottocartelle per posizione).
Puoi rilanciare il download quando vuoi: non riscarica i CV gia' presi
(usa il checkpoint in "logs").

CARICARE I CV IN CV SCREENER
----------------------------
Modo automatico (consigliato):
1. Doppio click su CARICA-SU-SERVER.cmd
2. Inserisci l'URL del server, es. http://192.168.1.10:8000
3. Attendi: i PDF vengono caricati uno per uno (a gruppi di 10).

Modo manuale:
1. Apri la web UI di CV Screener (URL del server nella LAN).
2. Trascina i PDF da "downloads" nell'area CV della pagina.

Poi, nella web UI: scrivi il profilo target e avvia lo screening.

NOTE
----
- Se Chrome e' aperto, la copia del profilo puo' essere incompleta:
  chiudilo prima di avviare.
- Se compare "Profile Chrome non trovato", apri Chrome almeno una volta
  e accedi a Indeed.
- La cartella "chrome-profile-copy" contiene una copia della sessione:
  non condividerla e cancellala quando non serve.

PRIVACY
-------
I CV scaricati restano sul tuo PC finche' non li carichi sul server
CV Screener della LAN.
'@
[IO.File]::WriteAllText((Join-Path $Staging "LEGGIMI.txt"), $readme, $utf8Bom)

Write-Host "==> Comprimo in $ZipPath"
$tar = Get-Command tar.exe -ErrorAction SilentlyContinue
if ($tar) {
    # tar.exe produce entry con separatore "/" (Compress-Archive di PS 5.1 usa "\")
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
