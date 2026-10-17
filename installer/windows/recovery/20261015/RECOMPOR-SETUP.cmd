@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0RECOMPOR-SETUP.ps1"
if errorlevel 1 (
  echo Falha na verificacao do pacote. Verifique se baixou todas as partes.
  pause
  exit /b 1
)
echo Instalador verificado. Leia as notas antes de executar.
pause
