import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .core.config import settings
from .db import store
from .services.demo import ensure_demo_close

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    ensure_demo_close()
    yield
    # Hand pooled connections back to Postgres rather than leaving the server to time
    # them out after the process is gone.
    store.close_pool()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # The dev server runs on 5180; the old allowlist only had 5173, so every browser
    # call would have been blocked even once the frontend started making them.
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Needed so the frontend can read the export filename off the download response.
    expose_headers=["Content-Disposition"],
)

app.include_router(router)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": settings.app_name, "status": "ok"}
