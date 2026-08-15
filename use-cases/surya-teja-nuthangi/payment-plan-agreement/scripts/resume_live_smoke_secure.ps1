$ErrorActionPreference = "Stop"
$secureKey = Read-Host "Enter SUPERDOCS_API_KEY to resume existing job (input hidden)" -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
$exitCode = 1

try {
    $env:SUPERDOCS_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    if ([string]::IsNullOrWhiteSpace($env:SUPERDOCS_API_KEY)) {
        throw "SUPERDOCS_API_KEY was empty; no request was made."
    }
    & (Join-Path $PSScriptRoot "..\..\.venv\Scripts\python.exe") (Join-Path $PSScriptRoot "resume_live_smoke.py")
    $exitCode = $LASTEXITCODE
} finally {
    Remove-Item Env:SUPERDOCS_API_KEY -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
}

exit $exitCode
