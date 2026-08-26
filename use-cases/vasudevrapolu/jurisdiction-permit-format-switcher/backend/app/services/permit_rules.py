from dataclasses import dataclass
from app.schemas.permit import ProjectRecord, PermitGap

@dataclass(frozen=True)
class Jurisdiction:
    id: str
    name: str
    packet_title: str
    required_forms: tuple[dict, ...]
    plan_notes: tuple[str, ...]
    attachments: tuple[dict, ...]
    signature_blocks: tuple[str, ...]
    requirements: tuple[dict, ...]

JURISDICTIONS = {
    "sunvale": Jurisdiction(
        id="sunvale", name="Sunvale County", packet_title="Residential PV Permit Packet",
        required_forms=(
            {"id":"PV-101","label":"Solar Permit Application","fields":["owner_name","address","system_kw","module_count","inverter_model","license_number"]},
            {"id":"ELEC-22","label":"Electrical Service Declaration","fields":["service_amps","inverter_model"]},
        ),
        plan_notes=("Array layout and equipment schedule shall be shown on the plan set.", "Provide roof attachment detail and conductor routing note."),
        attachments=(
            {"id":"site-plan","label":"Site plan"}, {"id":"single-line","label":"Electrical single-line diagram"},
            {"id":"equipment","label":"Equipment specification sheets"},
        ),
        signature_blocks=("Property owner signature", "Licensed contractor signature"),
        requirements=(
            {"code":"LIC-01","label":"Contractor license","field":"license_number","reason":"Sunvale requires the contractor license number on the permit application."},
            {"code":"ROOF-01","label":"Roof attachment detail","field":"roof_type","reason":"A roof-specific attachment note is required."},
        ),
    ),
    "ridgefield": Jurisdiction(
        id="ridgefield", name="Ridgefield City", packet_title="Residential Solar + Storage Permit Set",
        required_forms=(
            {"id":"R-RES","label":"Renewable Energy Permit","fields":["owner_name","address","system_kw","battery","license_number"]},
            {"id":"R-FIRE","label":"Fire Access & Storage Declaration","fields":["battery","roof_type"]},
            {"id":"R-STR","label":"Structural Attachment Sheet","fields":["roof_type","module_count"]},
        ),
        plan_notes=("Show fire access pathways on all roof planes.", "If storage is proposed, identify battery location, clearance and disconnect.", "Include structural attachment schedule."),
        attachments=(
            {"id":"site-plan","label":"Site plan with fire access path"}, {"id":"single-line","label":"Electrical single-line diagram"},
            {"id":"structural","label":"Structural attachment schedule"}, {"id":"battery","label":"Battery installation sheet"},
        ),
        signature_blocks=("Owner authorization", "Installer responsible professional signature"),
        requirements=(
            {"code":"LIC-02","label":"Installer license","field":"license_number","reason":"Ridgefield requires an installer license on the responsible-professional block."},
            {"code":"BAT-01","label":"Battery data","field":"battery","reason":"Battery-specific form and attachment are required only when storage is proposed."},
        ),
    ),
}

def get_jurisdiction(jurisdiction_id: str) -> Jurisdiction:
    try:
        return JURISDICTIONS[jurisdiction_id]
    except KeyError as exc:
        raise ValueError(f"Unknown jurisdiction: {jurisdiction_id}") from exc

def evaluate_gaps(project: ProjectRecord, jurisdiction: Jurisdiction) -> list[PermitGap]:
    gaps: list[PermitGap] = []
    for req in jurisdiction.requirements:
        value = getattr(project, req["field"])
        if req["code"] in {"BAT-01"} and not project.battery:
            continue
        if value in (None, "", 0):
            gaps.append(PermitGap(code=req["code"], label=req["label"], reason=req["reason"], blocking=True))
    return gaps
