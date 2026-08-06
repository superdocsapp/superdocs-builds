from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field, field_validator


def _require_non_empty(value: str, field_name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field_name} is required and cannot be empty")
    return value.strip()


class Violation(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    description: str
    location: str | None = None
    observed_on: date | None = None

    @field_validator("code")
    @classmethod
    def code_required(cls, value: str) -> str:
        return _require_non_empty(value, "code")

    @field_validator("description")
    @classmethod
    def description_required(cls, value: str) -> str:
        return _require_non_empty(value, "description")


class CorrectiveItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    finding: str
    corrective_action: str
    responsible_party: str
    completion_target: str | None = None
    evidence: str | None = None

    @field_validator("code")
    @classmethod
    def code_required(cls, value: str) -> str:
        return _require_non_empty(value, "code")

    @field_validator("finding")
    @classmethod
    def finding_required(cls, value: str) -> str:
        return _require_non_empty(value, "finding")

    @field_validator("corrective_action")
    @classmethod
    def corrective_action_required(cls, value: str) -> str:
        return _require_non_empty(value, "corrective_action")

    @field_validator("responsible_party")
    @classmethod
    def responsible_party_required(cls, value: str) -> str:
        return _require_non_empty(value, "responsible_party")


class CorrectivePlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    restaurant: str
    inspection_date: date
    health_department: str
    items: tuple[CorrectiveItem, ...]

    @field_validator("restaurant")
    @classmethod
    def restaurant_required(cls, value: str) -> str:
        return _require_non_empty(value, "restaurant")

    @field_validator("health_department")
    @classmethod
    def department_required(cls, value: str) -> str:
        return _require_non_empty(value, "health_department")


class CodeCoverage(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    status: Literal["covered", "incomplete"]
    reasons: tuple[str, ...] = ()

    @computed_field
    @property
    def is_complete(self) -> bool:
        return self.status == "covered"


class CoverageReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    codes: tuple[CodeCoverage, ...]
    uninvited_codes: tuple[str, ...] = ()

    @computed_field
    @property
    def is_complete(self) -> bool:
        return bool(self.codes) and not self.uninvited_codes and all(
            code.is_complete for code in self.codes
        )

    @computed_field
    @property
    def missing_codes(self) -> tuple[str, ...]:
        return tuple(
            code.code
            for code in self.codes
            if any(reason.startswith("code not present") for reason in code.reasons)
        )
