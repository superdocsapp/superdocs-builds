from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class ProjectCreate(BaseModel):
    name: str = Field(
        min_length=3,
        max_length=100
    )

    license: Literal[
        "MIT",
        "Apache-2.0",
        "GPL-3.0",
        "BSD-3-Clause"
    ]

    governance_model: Literal[
        "Maintainer-led",
        "BDFL",
        "Community-elected",
        "Foundation-governed"
    ]

    contact_email: EmailStr


class ProjectResponse(BaseModel):
    id: int
    name: str
    license: str
    governance_model: str
    contact_email: EmailStr

    class Config:
        from_attributes = True