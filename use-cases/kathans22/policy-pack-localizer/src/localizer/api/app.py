"""FastAPI app factory. Routes are thin — every response is built from
service.py / config.py, the same functions the CLI calls. Nothing here
reimplements lock/generate/verify/amend logic.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .. import packs
from .routes import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Policy Pack Localizer",
        description="Field-office policy pack localizer, built on SuperDocs.",
    )
    app.include_router(router)

    # Serve generated exports (out/) directly, so the Packs screen can link
    # straight to a .md/.docx download. mkdir first: a fresh clone has no
    # out/ yet (B6 — stranger clone-to-working must not crash on startup),
    # and StaticFiles requires the directory to exist at mount time.
    packs.OUT_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/exports", StaticFiles(directory=packs.OUT_DIR), name="exports")

    return app


app = create_app()
