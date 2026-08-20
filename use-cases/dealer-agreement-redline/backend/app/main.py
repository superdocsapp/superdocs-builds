from fastapi import FastAPI

from app.api.redline import router as redline_router
from app.api.poc import router as poc_router
from app.api.superdocs import router as superdocs_router
from contextlib import asynccontextmanager

from app.db.init_db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(
    title="Dealer Agreement Redline Desk",
    lifespan=lifespan,
)


app.include_router(superdocs_router)
app.include_router(poc_router)
app.include_router(redline_router)

@app.get("/health")
async def health():
    return {
        "status": "ok",
    }