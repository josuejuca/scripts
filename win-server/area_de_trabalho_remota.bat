@echo off
title Ativando Área de Trabalho Remota no Windows Server 2022
color 0A

echo.
echo Ativando Remote Desktop...
reg add "HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server" /v fDenyTSConnections /t REG_DWORD /d 0 /f

echo.
echo Ativando Nível de Autenticacao da Área de Trabalho Remota (NLA)...
reg add "HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp" /v UserAuthentication /t REG_DWORD /d 1 /f

echo.
echo Liberando porta 3389 no Firewall...
netsh advfirewall firewall set rule group="Área de trabalho remota" new enable=Yes

echo.
echo Serviço de Remote Desktop será reiniciado...
net stop TermService /y
net start TermService

echo.
echo Area de Trabalho Remota ativada com sucesso!
echo Agora verifique se seu roteador ou rede permite acesso externo na porta 3389.
echo.
pause
