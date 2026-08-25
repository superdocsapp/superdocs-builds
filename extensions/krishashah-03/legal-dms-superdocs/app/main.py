"""
App entrypoint: `uvicorn app.main:app --reload`

Wiring is intentionally simple (module-level singletons) since this is a
take-home integration, not a production multi-tenant service. Swapping to
per-request DMS/SuperDocs instances (e.g. one SuperDocs API key per law
firm) means changing get_dms/get_superdocs/get_workflow below - nothing in
app/routers or app/services needs to change.
"""
from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.dms.seed import build_seeded_store
from app.dms.store import DMSStore
from app.routers.documents import register_routes
from app.services.workflow import DocumentWorkflow
from app.superdocs.client import SuperDocsClient

app = FastAPI(
    title="Legal DMS <-> SuperDocs Integration",
    description=(
        "SuperDocs Round 2 engineer task - assigned build: legal "
        "document-management system integration. Built by Krisha Shah."
    ),
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
_dms_store = build_seeded_store()
_superdocs_client: SuperDocsClient | None = None
_workflow: DocumentWorkflow | None = None


def get_dms() -> DMSStore:
    return _dms_store


def get_superdocs() -> SuperDocsClient:
    global _superdocs_client
    if _superdocs_client is None:
        if not settings.superdocs_api_key:
            raise RuntimeError(
                "SUPERDOCS_API_KEY is not set. Copy .env.example to .env and "
                "add a key from use.superdocs.app -> Settings -> API Keys."
            )
        _superdocs_client = SuperDocsClient(
            api_key=settings.superdocs_api_key,
            base_url=settings.superdocs_base_url,
        )
    return _superdocs_client


def get_workflow() -> DocumentWorkflow:
    """
    MUST be a singleton. DocumentWorkflow carries per-checkout session state
    (which HTML the session started from, and whether any edit was actually
    approved) that spans four separate HTTP requests: checkout -> edit ->
    review -> checkin. Returning a fresh instance per request - as this did
    originally - silently emptied that state between every call, so checkin
    always believed nothing had been approved and filed the PREVIOUS
    version's bytes as the new version: HTTP 200, new version number, stale
    content, no error anywhere. See tests/test_app_wiring.py.
    """
    global _workflow
    if _workflow is None:
        _workflow = DocumentWorkflow(get_dms(), get_superdocs())
    return _workflow


api_router = APIRouter()
register_routes(api_router, get_dms, get_superdocs, get_workflow)
app.include_router(api_router)


@app.get("/health")
def health() -> dict:
    return {"status": "healthy"}
