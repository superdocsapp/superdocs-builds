"""Run the reviewer API: python -m job_architecture.web"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("JOB_ARCH_HOST", "127.0.0.1")
    port = int(os.environ.get("JOB_ARCH_PORT", "8000"))
    uvicorn.run(
        "job_architecture.web.app:app",
        host=host,
        port=port,
        reload=os.environ.get("JOB_ARCH_RELOAD", "").lower() in {"1", "true", "yes"},
    )


if __name__ == "__main__":
    main()
