from pydantic import BaseModel, Field

class ProjectRecord(BaseModel):
    project_name: str = "Sunrise Residence"
    address: str
    city: str
    state: str
    postal_code: str
    system_kw: float = Field(gt=0)
    module_count: int = Field(gt=0)
    inverter_model: str
    roof_type: str
    service_amps: int = Field(gt=0)
    battery: bool = False
    owner_name: str
    contractor_name: str
    license_number: str | None = None

class PermitRequest(BaseModel):
    project: ProjectRecord
    master_narrative: str = ""
    jurisdiction_id: str

class PermitGap(BaseModel):
    code: str
    label: str
    reason: str
    blocking: bool = True

class PermitPacket(BaseModel):
    jurisdiction_id: str
    jurisdiction_name: str
    packet_title: str
    forms: list[dict]
    plan_notes: list[str]
    attachments: list[dict]
    signature_blocks: list[str]
    gaps: list[PermitGap]
    checklist: list[dict]
    html: str
    superdocs_used: bool = False
