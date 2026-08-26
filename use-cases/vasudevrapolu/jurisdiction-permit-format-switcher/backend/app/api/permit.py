from fastapi import APIRouter
from app.schemas.permit import PermitRequest, PermitPacket
from app.services.permit_service import PermitService

router=APIRouter(prefix="/api/permit", tags=["permit"])
service=PermitService()

@router.post("/generate", response_model=PermitPacket)
async def generate(req: PermitRequest):
    return await service.generate(req)
