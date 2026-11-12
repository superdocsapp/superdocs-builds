from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.poc import router as poc_router
from app.api.redline import router as redline_router
from app.api.superdocs import router as superdocs_router


app = FastAPI(
    title="Dealer Agreement Redline",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(poc_router)
app.include_router(redline_router)
app.include_router(superdocs_router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
    }