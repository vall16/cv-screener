@echo off
chcp 65001 >nul
echo Attivazione Desktop Remoto...
reg add "HKLM\System\CurrentControlSet\Control\Terminal Server" /v fDenyTSConnections /t REG_DWORD /d 0 /f
netsh advfirewall firewall set rule group="Remote Desktop" new enable=yes
sc config TermService start= auto
net start TermService
echo.
echo Fatto! Desktop Remoto attivo su porta 3389.
pause
