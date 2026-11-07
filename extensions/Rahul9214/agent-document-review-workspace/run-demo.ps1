Write-Host "Starting SuperDocs Agent Review demo at http://localhost:8031" -ForegroundColor Cyan
Set-Location "$PSScriptRoot\demo"
python -m http.server 8031
