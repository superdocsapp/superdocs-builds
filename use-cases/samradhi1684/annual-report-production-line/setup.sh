#!/usr/bin/env bash
set -e

echo "=== Annual Report Production Line — Setup ==="

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required but not found."
    exit 1
fi

# Create and activate virtual environment if not already in one
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Creating virtual environment (.venv)..."
    python3 -m venv .venv
    source .venv/bin/activate
    echo "Virtual environment created and activated."
else
    echo "Already in a virtual environment: $VIRTUAL_ENV"
fi

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Check for API key
if [ -z "$SUPERDOCS_API_KEY" ]; then
    echo ""
    echo "SUPERDOCS_API_KEY is not set."
    echo "Set it before running the workflow:"
    echo ""
    echo "  export SUPERDOCS_API_KEY=\"your-api-key\""
    echo ""
else
    echo "SUPERDOCS_API_KEY is set."
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Activate the environment next time with:"
echo "  source .venv/bin/activate"
echo ""
echo "Run the MCP server:"
echo "  python3 mcp_server.py"
echo ""
echo "Or run the pipeline steps individually:"
echo "  python3 test_multidoc.py       # upload documents"
echo "  python3 consistency_check.py  # check number consistency"
echo "  python3 house_style.py        # check house style"
echo "  python3 export.py             # export PDF + HTML"