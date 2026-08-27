# Annual Report Production Line — Setup (PowerShell)

Write-Host "=== Annual Report Production Line — Setup ===" -ForegroundColor Cyan

# Check Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Error: python is required but not found." -ForegroundColor Red
    exit 1
}

# Create and activate virtual environment if not already in one
if (-not $env:VIRTUAL_ENV) {
    Write-Host "Creating virtual environment (.venv)..."
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    Write-Host "Virtual environment created and activated." -ForegroundColor Green
} else {
    Write-Host "Already in a virtual environment: $env:VIRTUAL_ENV" -ForegroundColor Green
}

# Install dependencies
Write-Host "Installing dependencies..."
pip install -r requirements.txt

# Check for API key
if (-not $env:SUPERDOCS_API_KEY) {
    Write-Host ""
    Write-Host "SUPERDOCS_API_KEY is not set." -ForegroundColor Yellow
    Write-Host "Set it before running the workflow:"
    Write-Host ""
    Write-Host '  $env:SUPERDOCS_API_KEY="your-api-key"'
    Write-Host ""
} else {
    Write-Host "SUPERDOCS_API_KEY is set." -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Activate the environment next time with:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "Run the MCP server:"
Write-Host "  python mcp_server.py"
Write-Host ""
Write-Host "Or run the pipeline steps individually:"
Write-Host "  python test_multidoc.py       # upload documents"
Write-Host "  python consistency_check.py  # check number consistency"
Write-Host "  python house_style.py        # check house style"
Write-Host "  python export.py             # export PDF + HTML"