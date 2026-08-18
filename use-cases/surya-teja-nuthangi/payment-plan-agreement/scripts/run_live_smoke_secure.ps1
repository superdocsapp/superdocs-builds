$ErrorActionPreference = "Stop"
$secureKey = Read-Host "Enter replacement SUPERDOCS_API_KEY (input hidden)" -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
$exitCode = 1

try {
    $env:SUPERDOCS_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    if ([string]::IsNullOrWhiteSpace($env:SUPERDOCS_API_KEY)) {
        throw "SUPERDOCS_API_KEY was empty; no live request was made."
    }
    & (Join-Path $PSScriptRoot "..\..\.venv\Scripts\python.exe") (Join-Path $PSScriptRoot "live_smoke.py")
    $exitCode = $LASTEXITCODE
} finally {
    Remove-Item Env:SUPERDOCS_API_KEY -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
}

exit $exitCode
