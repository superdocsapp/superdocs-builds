from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Frequency(str, Enum):
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


class LateFeeKind(str, Enum):
    NONE = "none"
    FIXED = "fixed"
    PERCENT = "percent"


class Party(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    legal_name: str = Field(min_length=1)
    display_name: str | None = None
    address: str | None = None


class LateFee(BaseModel):
    kind: LateFeeKind = LateFeeKind.NONE
    amount: Decimal | None = None
    percent: Decimal | None = None
    grace_days: int = Field(default=0, ge=0, le=365)

    @model_validator(mode="after")
    def valid_configuration(self) -> "LateFee":
        if self.kind == LateFeeKind.NONE and (self.amount is not None or self.percent is not None):
            raise ValueError("no late-fee value is allowed when kind is none")
        if self.kind == LateFeeKind.FIXED and (self.amount is None or self.amount <= 0 or self.percent is not None):
            raise ValueError("fixed late fee requires only a positive amount")
        if self.kind == LateFeeKind.PERCENT and (self.percent is None or not Decimal("0") < self.percent <= Decimal("25") or self.amount is not None):
            raise ValueError("percent late fee requires only a percentage in (0, 25]")
        return self


class PlanTerms(BaseModel):
    currency: str
    original_balance: Decimal
    upfront_payment: Decimal = Decimal("0")
    installment_count: int = Field(ge=1, le=120)
    frequency: Frequency
    first_due_date: date
    late_fee: LateFee = Field(default_factory=LateFee)
    agreement_date: date
    reference_id: str | None = Field(default=None, max_length=100)
    additional_terms: str | None = Field(default=None, max_length=4000)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()


class CreatePlanRequest(BaseModel):
    creditor: Party
    debtor: Party
    terms: PlanTerms


class Installment(BaseModel):
    number: int
    due_date: date
    amount: Decimal
    balance_after: Decimal


class PaymentPlan(BaseModel):
    creditor: Party
    debtor: Party
    terms: PlanTerms
    financed_balance: Decimal
    installments: list[Installment]
    total_scheduled: Decimal
    final_due_date: date
    semantic_fingerprint: str
    warnings: list[str] = Field(default_factory=list)


class AgreementProjection(BaseModel):
    title: str
    intro_fields: dict[str, str]
    schedule_columns: list[str]
    schedule_rows: list[dict[str, str]]
    term_bindings: dict[str, str]
    signature_fields: dict[str, str]
    prose_payment_terms: str


class ProposedChange(BaseModel):
    change_id: str
    operation: Literal["edit", "create", "delete"]
    chunk_id: str | None = None
    old_html: str | None = None
    new_html: str | None = None
    ai_explanation: str | None = None
    blocked: bool = False


class ReviewDecision(BaseModel):
    change_id: str
    approved: bool
    feedback: str | None = None
