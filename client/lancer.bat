@echo off
rem Double-clic : envoi automatique (demande la cle au premier lancement).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0envoi-guilde.ps1"
pause
