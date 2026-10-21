"""Development server runner"""
import sys
import os
from pathlib import Path

os.environ["PYTHONUNBUFFERED"] = "1"
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

sys.path.insert(0, str(Path(__file__).parent.parent))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "true").lower() in ("true", "1", "yes")
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=port,
        reload=reload,
        reload_dirs=["backend"],
        log_level="info",
    )
