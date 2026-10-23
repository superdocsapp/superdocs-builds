"""Company research API endpoints."""

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_company_research_service
from app.core.logging import get_logger
from app.schemas.company import CompanyResearchRequest, CompanyResearchResponse
from app.services.company.company_research import CompanyResearchService

router = APIRouter()
logger = get_logger(__name__)


@router.post("/research", response_model=CompanyResearchResponse)
async def research_company(
    payload: CompanyResearchRequest,
    service: CompanyResearchService = Depends(get_company_research_service),
) -> CompanyResearchResponse:
    """
    Research a company and return structured JSON.

    Unavailable fields are returned as exactly `"Unknown"`.
    Facts are extracted only from fetched public evidence — never invented.
    """
    result = await service.research_structured(payload)
    logger.info(
        "API company research name=%s sources=%s",
        result.company_name,
        len(result.sources),
    )
    return result


@router.get("/research", response_model=CompanyResearchResponse)
async def research_company_get(
    company_name: str = Query(..., min_length=1),
    company_url: str | None = Query(default=None),
    service: CompanyResearchService = Depends(get_company_research_service),
) -> CompanyResearchResponse:
    """GET variant for quick company research lookups."""
    payload = CompanyResearchRequest(company_name=company_name, company_url=company_url)
    return await service.research_structured(payload)
