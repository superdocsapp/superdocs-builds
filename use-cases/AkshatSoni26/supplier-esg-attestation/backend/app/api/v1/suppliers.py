from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import SupplierModel
from app.schemas.supplier import SupplierCreate, SupplierUpdate, SupplierResponse

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])


@router.get("", response_model=list[SupplierResponse])
async def list_suppliers(db: AsyncSession = Depends(get_db)):
    """List all registered suppliers."""
    stmt = select(SupplierModel).order_by(SupplierModel.name)
    res = await db.execute(stmt)
    return res.scalars().all()


@router.get("/{supplier_id}", response_model=SupplierResponse)
async def get_supplier(supplier_id: str, db: AsyncSession = Depends(get_db)):
    """Get single supplier by ID."""
    stmt = select(SupplierModel).where(SupplierModel.id == supplier_id)
    res = await db.execute(stmt)
    supplier = res.scalar_one_or_none()
    if not supplier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    return supplier


@router.post("", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
async def create_supplier(payload: SupplierCreate, db: AsyncSession = Depends(get_db)):
    """Register a new supplier."""
    existing = await db.execute(select(SupplierModel).where(SupplierModel.code == payload.code))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Supplier code already exists")

    supplier = SupplierModel(
        name=payload.name,
        code=payload.code,
        tier=payload.tier.value,
        region=payload.region.value,
        country=payload.country,
        primary_contact_email=payload.primary_contact_email
    )
    db.add(supplier)
    await db.commit()
    await db.refresh(supplier)
    return supplier
