from __future__ import annotations
import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
SUPERDOCS_API_KEY = os.environ.get("SUPERDOCS_API_KEY")
SUPERDOCS_MCP_URL = os.environ.get("SUPERDOCS_MCP_URL", "https://api.superdocs.app/mcp/")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set — check your .env file")
if not SUPERDOCS_API_KEY:
    raise RuntimeError("SUPERDOCS_API_KEY is not set — check your .env file")