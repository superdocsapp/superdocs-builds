$ErrorActionPreference = "Stop"

function Assert-NativeSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed with exit code $LASTEXITCODE." }
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$envFile = Join-Path $root ".env"

if (-not (Test-Path -LiteralPath $venvPython)) {
    python -m venv (Join-Path $root ".venv")
}
& $venvPython -m pip install --disable-pip-version-check -q -r (Join-Path $root "requirements.txt")
Assert-NativeSuccess "dependency installation"

if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Create .env from .env.example and set SUPERDOCS_API_KEY before starting."
}
foreach ($line in Get-Content -LiteralPath $envFile) {
    if ($line -match '^(SUPERDOCS_API_KEY|SUPERDOCS_MCP_URL|SUPERDOCS_SIGNED_URL_HOSTS)=(.+)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim(), "Process")
    }
}
if ([string]::IsNullOrWhiteSpace($env:SUPERDOCS_API_KEY)) {
    throw "SUPERDOCS_API_KEY is missing from .env."
}

Set-Location -LiteralPath $root
& $venvPython -m uvicorn app:app --host 127.0.0.1 --port 8080
Assert-NativeSuccess "local server"
