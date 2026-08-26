import pytest
from app.services.permit_service import PermitService
from app.schemas.permit import PermitRequest, ProjectRecord

@pytest.mark.asyncio
async def test_two_jurisdictions_differ_without_reentry():
    project=ProjectRecord(address="10 Main St",city="Demo",state="TS",postal_code="500001",system_kw=6.4,module_count=16,inverter_model="INV-X",roof_type="asphalt-shingle",service_amps=200,owner_name="Synthetic Owner",contractor_name="Synthetic Solar",license_number="LIC-123")
    svc=PermitService()
    a=await svc.generate(PermitRequest(project=project,jurisdiction_id="sunvale"))
    b=await svc.generate(PermitRequest(project=project,jurisdiction_id="ridgefield"))
    assert a.jurisdiction_id != b.jurisdiction_id
    assert a.forms != b.forms
    assert a.plan_notes != b.plan_notes
    assert a.attachments != b.attachments

@pytest.mark.asyncio
async def test_missing_license_is_flagged_not_blank():
    project=ProjectRecord(address="10 Main St",city="Demo",state="TS",postal_code="500001",system_kw=6.4,module_count=16,inverter_model="INV-X",roof_type="tile",service_amps=200,owner_name="Synthetic Owner",contractor_name="Synthetic Solar")
    packet=await PermitService().generate(PermitRequest(project=project,jurisdiction_id="sunvale"))
    assert any(g.code == "LIC-01" for g in packet.gaps)
    assert "MISSING" in packet.html
