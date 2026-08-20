from datetime import date, timedelta
import importlib
import sys
import types
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Mock runtime before importing app.main to avoid requiring live PostgreSQL DB for unit/API tests
runtime = types.ModuleType("app.agents.runtime")
runtime.workflow = object()
sys.modules["app.agents.runtime"] = runtime

from app.db.session import Base, get_db
from app.main import app
from app.models.finding import Finding
from app.models.submittal import Submittal
from app.models.transmittal import Transmittal
from app.services.register import (
    create_register_item,
    generate_register,
    get_overdue_submittals,
    get_register,
    update_register_status,
)


@pytest.fixture
def db_session(tmp_path):
    db_path = tmp_path / "test_register.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


def test_1_create_one_register_item(db_session):
    req = {
        "title": "Flooring Product Data",
        "description": "Manufacturer technical sheet for resilient flooring",
        "specification_section": "09 65 00",
        "required_by": "Flooring Subcontractor",
        "required_form": "Product data / technical sheet",
        "source_evidence": "09 65 00 Rev 01 Section 1.04: Submit product data.",
        "specification_revision": "Rev 01",
        "due_date": date(2026, 9, 1),
    }

    item = create_register_item(db_session, "BROD-2026", req)
    db_session.commit()

    assert item.id is not None
    assert item.project_id == "BROD-2026"
    assert item.number == "SUB-001"
    assert item.title == "Flooring Product Data"
    assert item.status == "PENDING"
    assert item.register_status == "NOT_RECEIVED"


def test_2_generate_two_register_items(db_session):
    reqs = [
        {
            "title": "Flooring Product Data",
            "description": "Flooring spec details",
            "specification_section": "09 65 00",
            "required_by": "Flooring Subcontractor",
            "required_form": "Product data",
            "source_evidence": "09 65 00 Section 1.4",
            "specification_revision": "Rev 01",
        },
        {
            "title": "Fire Door Product Data",
            "description": "Fire door compliance sheet",
            "specification_section": "08 11 00",
            "required_by": "Door Subcontractor",
            "required_form": "Technical sheet",
            "source_evidence": "08 11 00 Section 1.3",
            "specification_revision": "Rev 01",
        },
    ]

    items = generate_register(db_session, "BROD-2026", reqs)
    assert len(items) == 2
    assert items[0].number == "SUB-001"
    assert items[1].number == "SUB-002"
    assert items[0].title == "Flooring Product Data"
    assert items[1].title == "Fire Door Product Data"


def test_3_register_number_generation(db_session):
    req1 = {
        "title": "Item One",
        "specification_section": "01 00 00",
        "source_evidence": "Spec evidence 1",
    }
    req2 = {
        "title": "Item Two",
        "specification_section": "02 00 00",
        "source_evidence": "Spec evidence 2",
    }
    i1 = create_register_item(db_session, "P1", req1)
    i2 = create_register_item(db_session, "P1", req2)

    assert i1.number == "SUB-001"
    assert i2.number == "SUB-002"


def test_4_required_fields_are_persisted(db_session):
    req = {
        "title": "Acoustic Tile Samples",
        "description": "Physical ceiling samples",
        "specification_section": "09 51 00",
        "required_by": "Acoustical Subcontractor",
        "required_form": "Sample",
        "source_evidence": "09 51 00 Section 1.05",
        "specification_revision": "Rev 03",
        "due_date": date(2026, 10, 15),
    }
    item = create_register_item(db_session, "P-100", req)
    db_session.commit()

    saved = db_session.query(Submittal).filter(Submittal.id == item.id).first()
    assert saved.title == "Acoustic Tile Samples"
    assert saved.description == "Physical ceiling samples"
    assert saved.specification_section == "09 51 00"
    assert saved.required_by == "Acoustical Subcontractor"
    assert saved.required_form == "Sample"
    assert saved.specification_revision == "Rev 03"
    assert saved.due_date == date(2026, 10, 15)


def test_5_source_evidence_is_persisted(db_session):
    evidence_text = "09 65 00 Rev 02, Section 1.04: Submit manufacturer product data for flooring material."
    req = {
        "title": "Flooring Product Data",
        "specification_section": "09 65 00",
        "source_evidence": evidence_text,
    }
    item = create_register_item(db_session, "BROD-2026", req)
    db_session.commit()

    saved = db_session.query(Submittal).filter(Submittal.id == item.id).first()
    assert saved.source_evidence == evidence_text


def test_6_missing_required_by_does_not_invent_value(db_session):
    req = {
        "title": "Hardware Certificate",
        "specification_section": "08 71 00",
        "source_evidence": "08 71 00 Section 1.2",
    }
    item = create_register_item(db_session, "P-1", req)
    assert item.required_by is None


def test_7_missing_due_date_remains_null(db_session):
    req = {
        "title": "Window Mock-up",
        "specification_section": "08 51 00",
        "source_evidence": "08 51 00 Section 1.5",
    }
    item = create_register_item(db_session, "P-1", req)
    assert item.due_date is None


def test_8_running_same_generation_twice_does_not_duplicate(db_session):
    reqs = [
        {
            "title": "Flooring Product Data",
            "specification_section": "09 65 00",
            "source_evidence": "09 65 00 Section 1.04",
        },
        {
            "title": "Fire Door Product Data",
            "specification_section": "08 11 00",
            "source_evidence": "08 11 00 Section 1.03",
        },
    ]

    first_run = generate_register(db_session, "BROD-2026", reqs)
    assert len(first_run) == 2
    assert db_session.query(Submittal).count() == 2

    second_run = generate_register(db_session, "BROD-2026", reqs)
    assert len(second_run) == 2
    assert db_session.query(Submittal).count() == 2
    assert first_run[0].id == second_run[0].id
    assert first_run[1].id == second_run[1].id


def test_9_specification_revision_updates_existing_requirement(db_session):
    rev1_reqs = [
        {
            "title": "Flooring Product Data",
            "specification_section": "09 65 00",
            "source_evidence": "09 65 00 Rev 01: Submit product data.",
            "specification_revision": "Rev 01",
        }
    ]
    generate_register(db_session, "BROD-2026", rev1_reqs)
    submittal_v1 = db_session.query(Submittal).filter(Submittal.number == "SUB-001").first()
    assert submittal_v1.specification_revision == "Rev 01"

    rev2_reqs = [
        {
            "title": "Flooring Product Data",
            "specification_section": "09 65 00",
            "source_evidence": "09 65 00 Rev 02: Updated requirements for resilient flooring data.",
            "specification_revision": "Rev 02",
        }
    ]
    generate_register(db_session, "BROD-2026", rev2_reqs)
    db_session.expire_all()

    submittals = db_session.query(Submittal).all()
    assert len(submittals) == 1
    assert submittals[0].number == "SUB-001"
    assert submittals[0].specification_revision == "Rev 02"
    assert "Rev 02" in submittals[0].source_evidence


def test_10_genuinely_new_requirement_creates_new_register_item(db_session):
    rev1_reqs = [
        {
            "title": "Flooring Product Data",
            "specification_section": "09 65 00",
            "source_evidence": "09 65 00 Rev 01",
            "specification_revision": "Rev 01",
        }
    ]
    generate_register(db_session, "BROD-2026", rev1_reqs)

    rev2_reqs = [
        {
            "title": "Flooring Product Data",
            "specification_section": "09 65 00",
            "source_evidence": "09 65 00 Rev 02",
            "specification_revision": "Rev 02",
        },
        {
            "title": "Installation Instructions",
            "specification_section": "09 65 00",
            "source_evidence": "09 65 00 Rev 02 Section 3.01: Submit manufacturer installation guide.",
            "specification_revision": "Rev 02",
        },
    ]
    generate_register(db_session, "BROD-2026", rev2_reqs)

    submittals = db_session.query(Submittal).order_by(Submittal.number.asc()).all()
    assert len(submittals) == 2
    assert submittals[0].number == "SUB-001"
    assert submittals[0].title == "Flooring Product Data"
    assert submittals[1].number == "SUB-002"
    assert submittals[1].title == "Installation Instructions"


def test_11_register_status_starts_as_not_received(db_session):
    req = {
        "title": "Sample Submittal",
        "specification_section": "01 33 00",
        "source_evidence": "01 33 00 Section 1.1",
    }
    item = create_register_item(db_session, "BROD-2026", req)
    assert item.register_status == "NOT_RECEIVED"


def test_12_register_status_can_move_to_received(db_session):
    req = {
        "title": "Sample Submittal",
        "specification_section": "01 33 00",
        "source_evidence": "01 33 00 Section 1.1",
    }
    item = create_register_item(db_session, "BROD-2026", req)
    updated = update_register_status(db_session, item, "RECEIVED")
    assert updated.register_status == "RECEIVED"


def test_13_invalid_register_status_is_rejected(db_session):
    req = {
        "title": "Sample Submittal",
        "specification_section": "01 33 00",
        "source_evidence": "01 33 00 Section 1.1",
    }
    item = create_register_item(db_session, "BROD-2026", req)
    with pytest.raises(ValueError, match="Unsupported register status"):
        update_register_status(db_session, item, "INVALID_STATE")


def test_14_reviewed_items_are_not_considered_overdue(db_session):
    today = date(2026, 8, 19)
    past_due = today - timedelta(days=5)

    req = {
        "title": "Past Due Reviewed Submittal",
        "specification_section": "09 65 00",
        "source_evidence": "Spec",
        "due_date": past_due,
    }
    item = create_register_item(db_session, "BROD-2026", req)
    update_register_status(db_session, item, "REVIEWED")

    overdue = get_overdue_submittals(db_session, "BROD-2026", today)
    assert len(overdue) == 0


def test_15_unreviewed_items_past_due_date_are_considered_overdue(db_session):
    today = date(2026, 8, 19)
    past_due = today - timedelta(days=5)

    req = {
        "title": "Past Due Unreceived Submittal",
        "specification_section": "09 65 00",
        "source_evidence": "Spec",
        "due_date": past_due,
    }
    item = create_register_item(db_session, "BROD-2026", req)

    overdue = get_overdue_submittals(db_session, "BROD-2026", today)
    assert len(overdue) == 1
    assert overdue[0].id == item.id


def test_16_second_run_multi_document_and_project_scenario(db_session):
    # Second document/project test dataset (Section 23)
    project_id = "BROD-2026"
    concrete_reqs = [
        {
            "title": "Concrete Mix Design",
            "description": "5000 PSI structural concrete mix design",
            "specification_section": "03 30 00",
            "required_by": "Concrete Subcontractor",
            "required_form": "Mix design calculation",
            "source_evidence": "03 30 00 Rev 01 Section 1.04.A: Submit mix designs for each class of concrete.",
            "specification_revision": "Rev 01",
            "due_date": date(2026, 8, 1),
        },
        {
            "title": "Test Reports",
            "description": "Compressive strength 7-day and 28-day test reports",
            "specification_section": "03 30 00",
            "required_by": "Independent Testing Agency",
            "required_form": "Test report",
            "source_evidence": "03 30 00 Rev 01 Section 1.04.B: Submit certified lab test reports.",
            "specification_revision": "Rev 01",
            "due_date": date(2026, 8, 15),
        },
        {
            "title": "Concrete Shop Drawings",
            "description": "Rebar placement and formwork shop drawings",
            "specification_section": "03 30 00",
            "required_by": "Reinforcing Steel Subcontractor",
            "required_form": "Shop Drawing",
            "source_evidence": "03 30 00 Rev 01 Section 1.04.C: Submit rebar placement drawings.",
            "specification_revision": "Rev 01",
            "due_date": date(2026, 9, 1),
        },
    ]

    items = generate_register(db_session, project_id, concrete_reqs)
    assert len(items) == 3
    assert [i.number for i in items] == ["SUB-001", "SUB-002", "SUB-003"]
    assert items[0].title == "Concrete Mix Design"
    assert items[1].title == "Test Reports"
    assert items[2].title == "Concrete Shop Drawings"

    # Mark first item as REVIEWED
    update_register_status(db_session, items[0], "REVIEWED")
    # Mark second item as RECEIVED
    update_register_status(db_session, items[1], "RECEIVED")

    # Evaluate overdue on 2026-08-19
    today = date(2026, 8, 19)
    overdue = get_overdue_submittals(db_session, project_id, today)
    # items[0] (mix design) due 08-01 but REVIEWED -> not overdue
    # items[1] (test reports) due 08-15 and RECEIVED -> OVERDUE!
    # items[2] (shop drawings) due 09-01 -> not overdue yet
    assert len(overdue) == 1
    assert overdue[0].title == "Test Reports"


def test_17_api_register_endpoints(client, db_session):
    req = {
        "title": "Flooring Product Data",
        "description": "Flooring technical sheet",
        "specification_section": "09 65 00",
        "required_by": "Flooring Subcontractor",
        "required_form": "Product data",
        "source_evidence": "09 65 00 Section 1.04",
        "specification_revision": "Rev 01",
        "due_date": date(2026, 8, 10),
    }
    item = create_register_item(db_session, "BROD-2026", req)
    db_session.commit()

    # GET /projects/BROD-2026/submittals
    res = client.get("/projects/BROD-2026/submittals")
    assert res.status_code == 200
    data = res.json()
    assert data["project_id"] == "BROD-2026"
    assert len(data["items"]) == 1
    assert data["items"][0]["number"] == "SUB-001"
    assert data["items"][0]["register_status"] == "NOT_RECEIVED"

    # PATCH /submittals/SUB-001/register-status
    patch_res = client.patch(
        "/submittals/SUB-001/register-status",
        json={"status": "RECEIVED"},
    )
    assert patch_res.status_code == 200
    patch_data = patch_res.json()
    assert patch_data["register_status"] == "RECEIVED"

    # PATCH with invalid status -> 422
    invalid_patch = client.patch(
        "/submittals/SUB-001/register-status",
        json={"status": "UNKNOWN_STATUS"},
    )
    assert invalid_patch.status_code in (400, 422)

    # GET /projects/BROD-2026/submittals/overdue
    overdue_res = client.get("/projects/BROD-2026/submittals/overdue")
    assert overdue_res.status_code == 200
    overdue_data = overdue_res.json()
    assert overdue_data["project_id"] == "BROD-2026"
    assert overdue_data["overdue_count"] == 1
    assert overdue_data["items"][0]["number"] == "SUB-001"


def test_18_api_generate_register_idempotency_and_revisions(client, db_session):
    # 1. Initial generation
    payload_v1 = {
        "requirements": [
            {
                "title": "Flooring Product Data",
                "description": "Manufacturer technical sheet",
                "specification_section": "09 65 00",
                "required_by": "Flooring Subcontractor",
                "required_form": "Product data",
                "source_evidence": "09 65 00 Rev 01 Section 1.04",
                "specification_revision": "Rev 01",
            }
        ]
    }

    res1 = client.post("/projects/BROD-2026/submittals/register", json=payload_v1)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["project_id"] == "BROD-2026"
    assert data1["count"] == 1
    assert data1["items"][0]["number"] == "SUB-001"
    assert data1["items"][0]["register_status"] == "NOT_RECEIVED"
    first_id = data1["items"][0]["id"]

    # 2. Verify GET /projects/BROD-2026/submittals
    get1 = client.get("/projects/BROD-2026/submittals")
    assert get1.status_code == 200
    assert len(get1.json()["items"]) == 1

    # 3. Post exact same payload again (Idempotency)
    res2 = client.post("/projects/BROD-2026/submittals/register", json=payload_v1)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["count"] == 1
    assert data2["items"][0]["number"] == "SUB-001"
    assert data2["items"][0]["id"] == first_id

    # 4. Verify GET items count remains 1
    get2 = client.get("/projects/BROD-2026/submittals")
    assert get2.status_code == 200
    assert len(get2.json()["items"]) == 1

    # 5. Revision update via API (Rev 02)
    payload_v2 = {
        "requirements": [
            {
                "title": "Flooring Product Data",
                "description": "Manufacturer technical sheet",
                "specification_section": "09 65 00",
                "required_by": "Flooring Subcontractor",
                "required_form": "Product data / technical sheet",
                "source_evidence": "09 65 00 Rev 02 Section 1.04: Updated resilient flooring details",
                "specification_revision": "Rev 02",
            }
        ]
    }

    res3 = client.post("/projects/BROD-2026/submittals/register", json=payload_v2)
    assert res3.status_code == 200
    data3 = res3.json()
    assert data3["count"] == 1
    assert data3["items"][0]["id"] == first_id
    assert data3["items"][0]["number"] == "SUB-001"
    assert data3["items"][0]["specification_revision"] == "Rev 02"
    assert "Rev 02" in data3["items"][0]["source_evidence"]

    # 6. Add genuinely new requirement in Rev 02
    payload_v2_new = {
        "requirements": [
            {
                "title": "Flooring Product Data",
                "description": "Manufacturer technical sheet",
                "specification_section": "09 65 00",
                "required_by": "Flooring Subcontractor",
                "required_form": "Product data / technical sheet",
                "source_evidence": "09 65 00 Rev 02 Section 1.04: Updated resilient flooring details",
                "specification_revision": "Rev 02",
            },
            {
                "title": "Installation Instructions",
                "description": "Manufacturer installation guide",
                "specification_section": "09 65 00",
                "required_by": "Flooring Subcontractor",
                "required_form": "Installation Instructions",
                "source_evidence": "09 65 00 Rev 02 Section 3.01: Submit installation instructions",
                "specification_revision": "Rev 02",
            },
        ]
    }

    res4 = client.post("/projects/BROD-2026/submittals/register", json=payload_v2_new)
    assert res4.status_code == 200
    data4 = res4.json()
    assert data4["count"] == 2
    assert data4["items"][0]["number"] == "SUB-001"
    assert data4["items"][1]["number"] == "SUB-002"
    assert data4["items"][1]["title"] == "Installation Instructions"

    # 7. Final GET check
    get3 = client.get("/projects/BROD-2026/submittals")
    assert get3.status_code == 200
    assert len(get3.json()["items"]) == 2


def test_19_submittal_detail_endpoint(client, db_session):
    req = {
        "title": "Flooring Product Data",
        "specification_section": "09 65 00",
        "source_evidence": "09 65 00 Section 1.04",
    }
    item = create_register_item(db_session, "BROD-2026", req)
    db_session.commit()

    f = Finding(
        submittal_id=item.id,
        attribute="Thickness",
        requirement="3 mm",
        submitted_value="3 mm",
        result="PASS",
        specification_evidence="Spec",
        submission_evidence="Submittal",
        status="PENDING_REVIEW",
    )
    db_session.add(f)
    db_session.commit()

    res = client.get("/submittals/SUB-001")
    assert res.status_code == 200
    data = res.json()
    assert data["number"] == "SUB-001"
    assert data["finding_count"] == 1
    assert data["unresolved_finding_count"] == 1
    assert data["reviewed_finding_count"] == 0
    assert len(data["findings"]) == 1
    assert data["findings"][0]["attribute"] == "Thickness"

    res_404 = client.get("/submittals/SUB-999")
    assert res_404.status_code == 404


def test_20_lifecycle_received(client, db_session):
    req = {
        "title": "Flooring Product Data",
        "specification_section": "09 65 00",
        "source_evidence": "Spec",
    }
    item = create_register_item(db_session, "BROD-2026", req)
    db_session.commit()
    assert item.register_status == "NOT_RECEIVED"

    patch_res = client.patch(
        "/submittals/SUB-001/register-status",
        json={"status": "RECEIVED"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["register_status"] == "RECEIVED"


def test_21_lifecycle_under_review(client, db_session):
    req = {
        "title": "Flooring Product Data",
        "specification_section": "09 65 00",
        "source_evidence": "Spec",
    }
    item = create_register_item(db_session, "BROD-2026", req)
    db_session.commit()

    client.patch("/submittals/SUB-001/register-status", json={"status": "RECEIVED"})
    patch_res = client.patch(
        "/submittals/SUB-001/register-status",
        json={"status": "UNDER_REVIEW"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["register_status"] == "UNDER_REVIEW"


def test_22_finding_review_complete(client, db_session):
    req = {
        "title": "Flooring Product Data",
        "specification_section": "09 65 00",
        "source_evidence": "Spec",
    }
    item = create_register_item(db_session, "BROD-2026", req)
    f = Finding(
        submittal_id=item.id,
        attribute="Thickness",
        requirement="3 mm",
        submitted_value="3 mm",
        result="MATCH",
        specification_evidence="Spec",
        submission_evidence="Submittal",
        status="PENDING_REVIEW",
    )
    db_session.add(f)
    db_session.commit()

    rev_res = client.post(
        f"/findings/{f.id}/review",
        json={
            "reviewer": "Alice",
            "decision": "APPROVE",
            "comment": "Compliant",
        },
    )
    assert rev_res.status_code == 200

    db_session.refresh(item)
    assert item.register_status == "REVIEWED"
    assert item.status == "REVIEWED_COMPLIANT"


def test_23_partial_review(client, db_session):
    req = {
        "title": "Flooring Product Data",
        "specification_section": "09 65 00",
        "source_evidence": "Spec",
    }
    item = create_register_item(db_session, "BROD-2026", req)
    f1 = Finding(
        submittal_id=item.id,
        attribute="Thickness",
        requirement="3 mm",
        submitted_value="3 mm",
        result="MATCH",
        specification_evidence="Spec",
        submission_evidence="Submittal",
        status="PENDING_REVIEW",
    )
    f2 = Finding(
        submittal_id=item.id,
        attribute="Fire Rating",
        requirement="Class A",
        submitted_value="Class A",
        result="MATCH",
        specification_evidence="Spec",
        submission_evidence="Submittal",
        status="PENDING_REVIEW",
    )
    db_session.add_all([f1, f2])
    db_session.commit()

    client.post(
        f"/findings/{f1.id}/review",
        json={"reviewer": "Alice", "decision": "APPROVE"},
    )
    db_session.refresh(item)
    assert item.register_status == "UNDER_REVIEW"
    assert item.register_status != "REVIEWED"

    client.post(
        f"/findings/{f2.id}/review",
        json={"reviewer": "Alice", "decision": "APPROVE"},
    )
    db_session.refresh(item)
    assert item.register_status == "REVIEWED"


def test_24_clarification_blocks_reviewed(client, db_session):
    req = {
        "title": "Flooring Product Data",
        "specification_section": "09 65 00",
        "source_evidence": "Spec",
    }
    item = create_register_item(db_session, "BROD-2026", req)
    f = Finding(
        submittal_id=item.id,
        attribute="Thickness",
        requirement="3 mm",
        submitted_value="2.5 mm",
        result="DEVIATION",
        specification_evidence="Spec",
        submission_evidence="Submittal",
        status="PENDING_REVIEW",
    )
    db_session.add(f)
    db_session.commit()

    client.post(
        f"/findings/{f.id}/review",
        json={"reviewer": "Alice", "decision": "REQUEST_CLARIFICATION", "comment": "Need lab test"},
    )
    db_session.refresh(item)
    assert f.status == "CLARIFICATION_REQUESTED"
    assert item.register_status == "UNDER_REVIEW"
    assert item.register_status != "REVIEWED"


def test_25_overdue_unresolved_query(client, db_session):
    yesterday = date.today() - timedelta(days=1)
    req = {
        "title": "Overdue Requirement",
        "specification_section": "09 65 00",
        "source_evidence": "Spec",
        "due_date": yesterday,
    }
    item = create_register_item(db_session, "BROD-2026", req)
    db_session.commit()

    res = client.get("/projects/BROD-2026/submittals/overdue")
    assert res.status_code == 200
    data = res.json()
    assert data["overdue_count"] == 1
    assert data["items"][0]["number"] == "SUB-001"


def test_26_reviewed_item_excluded_from_overdue(client, db_session):
    yesterday = date.today() - timedelta(days=1)
    req = {
        "title": "Reviewed Requirement",
        "specification_section": "09 65 00",
        "source_evidence": "Spec",
        "due_date": yesterday,
    }
    item = create_register_item(db_session, "BROD-2026", req)
    update_register_status(db_session, item, "REVIEWED")

    res = client.get("/projects/BROD-2026/submittals/overdue")
    assert res.status_code == 200
    assert res.json()["overdue_count"] == 0


def test_27_transmittal_safety_block(client, db_session):
    req = {
        "title": "Flooring Product Data",
        "specification_section": "09 65 00",
        "source_evidence": "Spec",
    }
    item = create_register_item(db_session, "BROD-2026", req)
    f = Finding(
        submittal_id=item.id,
        attribute="Thickness",
        requirement="3 mm",
        submitted_value="2 mm",
        result="DEVIATION",
        specification_evidence="Spec",
        submission_evidence="Submittal",
        status="PENDING_REVIEW",
    )
    db_session.add(f)
    db_session.commit()

    res = client.post("/transmittals/SUB-001")
    assert res.status_code == 409
    assert "All findings must be reviewed before creating a transmittal." in res.json()["detail"]


def test_28_register_and_technical_status_separation(client, db_session):
    req = {
        "title": "Flooring Product Data",
        "specification_section": "09 65 00",
        "source_evidence": "Spec",
    }
    item = create_register_item(db_session, "BROD-2026", req)
    f = Finding(
        submittal_id=item.id,
        attribute="Thickness",
        requirement="3 mm",
        submitted_value="2.5 mm",
        result="DEVIATION",
        specification_evidence="Spec",
        submission_evidence="Submittal",
        status="PENDING_REVIEW",
    )
    db_session.add(f)
    db_session.commit()

    client.post(
        f"/findings/{f.id}/review",
        json={"reviewer": "Bob", "decision": "APPROVE", "comment": "Approved deviation"},
    )
    db_session.refresh(item)
    assert item.status == "REVIEWED_DEVIATION"
    assert item.register_status == "REVIEWED"


def test_29_manual_patch_reviewed_rejected_when_unresolved(client, db_session):
    req = {
        "title": "Flooring Product Data",
        "specification_section": "09 65 00",
        "source_evidence": "Spec",
    }
    item = create_register_item(db_session, "BROD-2026", req)
    f = Finding(
        submittal_id=item.id,
        attribute="Thickness",
        requirement="3 mm",
        submitted_value="2 mm",
        result="DEVIATION",
        specification_evidence="Spec",
        submission_evidence="Submittal",
        status="PENDING_REVIEW",
    )
    db_session.add(f)
    db_session.commit()

    res = client.patch(
        "/submittals/SUB-001/register-status",
        json={"status": "REVIEWED"},
    )
    assert res.status_code == 400
    assert "Cannot mark submittal as REVIEWED while findings remain unresolved" in res.json()["detail"]

