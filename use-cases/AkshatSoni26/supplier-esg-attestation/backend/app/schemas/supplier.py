from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr
from app.schemas.enums import SupplierTier, Region


class SupplierBase(BaseModel):
    name: str
    code: str
    tier: SupplierTier
    region: Region
    country: str
    primary_contact_email: EmailStr


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: str | None = None
    tier: SupplierTier | None = None
    region: Region | None = None
    country: str | None = None
    primary_contact_email: EmailStr | None = None


class SupplierResponse(SupplierBase):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
