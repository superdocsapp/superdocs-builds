$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPython = Join-Path $Backend ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
  $Python = $env:PYTHON
  if (-not $Python) {
    $Python = "py"
  }
  & $Python -3.12 -m venv (Join-Path $Backend ".venv")
}

Push-Location $Backend
& $VenvPython -m pip install -e ".[test]"
Pop-Location

Push-Location $Frontend
npm install
npm run build
Pop-Location

Push-Location $Backend
& $VenvPython -m uvicorn app.api:app --host 127.0.0.1 --port 8000
Pop-Location

