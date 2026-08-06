# Copy to .env and fill API keys
Copy-Item .env.example .env -ErrorAction SilentlyContinue
Write-Host "Bootstrap complete. Edit .env with your LLM keys."
