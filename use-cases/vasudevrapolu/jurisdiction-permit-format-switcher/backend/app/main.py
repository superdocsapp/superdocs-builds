from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.base import Base
from app.db.session import engine
from app.models import AgentRun
from app.api.health import router as health_router
from app.api.agent import router as agent_router
from app.api.permit import router as permit_router

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Document Intelligence + Permit Switcher",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(agent_router)
app.include_router(permit_router)