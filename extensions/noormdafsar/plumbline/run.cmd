@echo off
REM Plumbline for machines without a local Python. Same arguments as the CLI.
setlocal
set "P=%~dp0"
if "%P:~-1%"=="\" set "P=%P:~0,-1%"
docker run --rm -v "%P%:/app" -w /app python:3.12-slim python plumbline.py %*
endlocal
