@echo off
REM Renewal Desk review console. Opens on http://localhost:7000
setlocal
set "PROJECT=%~dp0"
if "%PROJECT:~-1%"=="\" set "PROJECT=%PROJECT:~0,-1%"
echo Starting the review console on http://localhost:7000  (Ctrl-C to stop)
docker run --rm -it -p 7000:7000 -v "%PROJECT%:/app" -w /app python:3.12-slim ^
  python renewal_desk.py serve --port 7000
endlocal
