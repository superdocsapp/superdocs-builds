from fastapi import APIRouter
from app.api.v1.suppliers import router as suppliers_router
from app.api.v1.issuance import router as issuance_router
from app.api.v1.ingestion import router as ingestion_router
from app.api.v1.assessments import router as assessments_router
from app.api.v1.review import router as review_router
from app.api.v1.followups import router as followups_router
from app.api.v1.reports import router as reports_router
from app.api.v1.superdocs import router as superdocs_router

api_v1_router = APIRouter()

api_v1_router.include_router(suppliers_router)
api_v1_router.include_router(issuance_router)
api_v1_router.include_router(ingestion_router)
api_v1_router.include_router(assessments_router)
api_v1_router.include_router(review_router)
api_v1_router.include_router(followups_router)
api_v1_router.include_router(reports_router)
api_v1_router.include_router(superdocs_router)
