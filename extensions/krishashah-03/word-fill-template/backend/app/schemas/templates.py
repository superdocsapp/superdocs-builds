from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TemplateFieldDef(BaseModel):
    type: str
    required: bool = False


class TemplateConditionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    condition_key: str
    operator: str
    expected_value: Any
    action: str


class TemplateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    category: str
    description: Optional[str] = None
    version: int
    is_active: bool


class TemplateDetail(TemplateSummary):
    file_path: str
    fields: dict[str, TemplateFieldDef]
    conditions: list[TemplateConditionOut] = []
