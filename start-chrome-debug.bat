@echo off
rem Avvia Chrome con remote debugging per il downloader Indeed.
rem Chiudi prima tutte le finestre Chrome (i tab si ripristinano).
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
