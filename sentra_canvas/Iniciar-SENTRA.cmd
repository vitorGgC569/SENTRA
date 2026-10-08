@echo off
setlocal
cd /d "%~dp0.."
set "SENTRA_EXE=%CD%\dist\sentra-canvas.exe"
if exist "%SENTRA_EXE%" (
  start "" "%SENTRA_EXE%" --root "%CD%"
  exit /b 0
)
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 -m sentra_canvas --root "%CD%"
) else (
  python -m sentra_canvas --root "%CD%"
)
if errorlevel 1 (
  echo.
  echo [SENTRA] Nao foi possivel iniciar a janela nativa do SENTRA.
  echo Confira o Python 3.12 e o WebView2/pywebview instalados.
  pause
)
endlocal
