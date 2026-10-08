@echo off
setlocal
chcp 65001 >nul 2>&1
set "SENTRA_ROOT=%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
if defined PYTHONPATH (
  set "PYTHONPATH=%SENTRA_ROOT%;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%SENTRA_ROOT%"
)
python -B -m sentra_cli %*
exit /b %ERRORLEVEL%
