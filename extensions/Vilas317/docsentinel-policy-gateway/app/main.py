from fastapi import FastAPI
from app.routes.gateway import router as gateway_router

app = FastAPI(title="DocSentinel Policy Gateway", version="1.0.0")
app.include_router(gateway_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}
