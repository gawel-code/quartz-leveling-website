@echo off
rem Double-clic : changer de cle ou d emplacement du fichier GuildExport.lua.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0envoi-guilde.ps1" -Reconfigurer
pause
