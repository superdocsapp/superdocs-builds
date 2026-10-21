@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  echo Python launcher "py" was not found.
  echo Install Python or run: python -m http.server 4173
  pause
  exit /b 1
)
start "SuperDocs Reality Engine Preview" /B py -m http.server 4173 --bind 127.0.0.1
timeout /t 1 /nobreak >nul
start "" "http://127.0.0.1:4173/preview/"
echo.
echo SuperDocs Reality Engine preview:
echo http://127.0.0.1:4173/preview/
echo.
echo Close this window to stop the preview server.
pause
