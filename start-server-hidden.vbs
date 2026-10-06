' Avvio minimizzato del server cv-screener all'accesso di Windows.
' Va copiato (o collegato) nella cartella:
'   %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
' Per fermare il server: chiudere la finestra "CV Screener - server LAN" dalla barra delle applicazioni.
Set shell = CreateObject("WScript.Shell")
shell.Run """C:\Users\vallo\cv-screener\start-server.bat""", 7, False
