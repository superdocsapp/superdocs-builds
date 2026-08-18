$ErrorActionPreference = "Stop"
$cache = Join-Path $PSScriptRoot "..\..\.cache\superdocs-llms-full.txt"
New-Item -ItemType Directory -Force -Path (Split-Path $cache) | Out-Null
$download = "$cache.download"
try {
    curl.exe -fSs https://docs.superdocs.app/llms-full.txt -o $download
    if ($LASTEXITCODE -ne 0) { throw "SuperDocs reference download failed with curl exit code $LASTEXITCODE." }
    if ((Get-Item $download).Length -lt 1000) { throw "Downloaded SuperDocs reference is unexpectedly small." }
    Move-Item -Force -LiteralPath $download -Destination $cache
} finally {
    if (Test-Path -LiteralPath $download) { Remove-Item -Force -LiteralPath $download }
}
Write-Output "Cached current SuperDocs reference at $cache"
