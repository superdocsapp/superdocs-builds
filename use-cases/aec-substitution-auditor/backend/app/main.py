from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.substitution import router as substitution_router
from app.database import engine, Base

app = FastAPI(title="AEC Substitution Auditor API")

@app.on_event("startup")
def on_startup():
    # Automatically generate tables (like substitution_runs) in the DB on startup
    Base.metadata.create_all(bind=engine)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(substitution_router, prefix="/api/substitution")

@app.get("/health")
def health_check():
    return {"status": "healthy"}
