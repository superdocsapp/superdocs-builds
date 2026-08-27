@echo off
REM Renewal Desk runner for machines without a local Python.
REM
REM Runs the CLI inside the official python:3.12-slim image with this folder
REM mounted. The project has no dependencies, so no image build is needed.
REM
REM Usage (from this folder):
REM     run.cmd plan
REM     run.cmd run --sample 1
REM     run.cmd review
REM     run.cmd decide ACM-1042 approve
REM     run.cmd report
REM
REM The key is read from .env in this folder (see .env.example).

setlocal
set "PROJECT=%~dp0"
if "%PROJECT:~-1%"=="\" set "PROJECT=%PROJECT:~0,-1%"

docker run --rm -it ^
  -v "%PROJECT%:/app" ^
  -w /app ^
  python:3.12-slim ^
  python renewal_desk.py %*

endlocal
