from pydantic import BaseModel, Field


class EmailContractCreate(BaseModel):
    negotiation_thread: str = Field(
        ...,
        min_length=1,
    )
    contract_type: str = Field(
        default="standard agreement",
        min_length=1,
    )


class EmailContractGenerate(BaseModel):
    contract_id: str
    negotiation_thread: str
    contract_type: str = "standard agreement"


class EmailContract(BaseModel):
    contract_id: str
    session_id: str
    contract_type: str
    status: str = "created"
    job_id: str | None = None
    pending_changes: list = Field(
        default_factory=list
    )
    response: dict | None = None