from fastapi import FastAPI, HTTPException

from app.services.superdocs import superdocs_client
from app.routes.document import router as documents_router
from app.routes.chat import router as chat_router
from app.routes.approval import router as approval_router
from app.routes.export import router as export_router
from app.routes.freight_claim import router as freight_claim_router
from app.routes.email_contract import router as email_contract_router

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="SuperDocs Task 2",
    description="Task 2 integration for SuperDocs",
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

app.include_router(documents_router)
app.include_router(chat_router)
app.include_router(approval_router)
app.include_router(freight_claim_router)
app.include_router(export_router)
app.include_router(email_contract_router)
@app.get("/")
async def root():
    return {
        "message": "SuperDocs Task 2 backend is running"
    }


@app.get("/health")
async def health(): 
    return {
        "status": "healthy"
    }


@app.get("/health/superdocs")
async def superdocs_health():
    try:
        sessions = await superdocs_client.list_sessions()

        return {
            "status": "connected",
            "sessions": sessions,
        }

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"SuperDocs connection failed: {str(error)}",
        )