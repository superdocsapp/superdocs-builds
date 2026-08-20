"""Phase 4F — Backend hardening tests.

These tests verify error boundaries, invalid transitions,
404 handling, and data-integrity constraints that were
added during Phase 4F.
"""

import sys
import types

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Mock LangGraph runtime before importing app.main
runtime = types.ModuleType("app.agents.runtime")
runtime.workflow = object()
sys.modules.setdefault("app.agents.runtime", runtime)

from app.db.session import Base, get_db
from app.main import app
from app.models.finding import Finding
from app.models.submittal import Submittal
from app.models.transmittal import Transmittal
from app.services.register import (
    create_register_item,
    generate_register,
    update_register_status,
    update_submittal_status,
)
from app.services.review import review_finding


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def db_session(tmp_path):
    db_path = tmp_path / "test_hardening.db"
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
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _seed_submittal(db_session, number="SUB-001", project_id="TEST-001"):
    """Create a minimal submittal for testing."""
    s = Submittal(
        project_id=project_id,
        number=number,
        title="Test Submittal",
        specification_section="01 00 00",
        source_evidence="Section 01 00 00 requires test submittal",
        status="PENDING",
        register_status="NOT_RECEIVED",
    )
    db_session.add(s)
    db_session.flush()
    return s


def _seed_finding(db_session, submittal_id, status="PENDING_REVIEW"):
    """Create a minimal finding for testing."""
    f = Finding(
        submittal_id=submittal_id,
        attribute="Test Attribute",
        requirement="Must comply",
        submitted_value="Compliant",
        result="COMPLIANT",
        specification_evidence="Spec says must comply",
        submission_evidence="Product data shows compliance",
        status=status,
    )
    db_session.add(f)
    db_session.flush()
    return f


# ============================================================
# 1. API — 404 responses
# ============================================================


class TestNotFoundResponses:
    """Verify 404 for non-existent resources."""

    def test_get_submittal_detail_not_found(self, client):
        r = client.get("/submittals/DOES-NOT-EXIST")
        assert r.status_code == 404

    def test_patch_register_status_not_found(self, client):
        r = client.patch(
            "/submittals/DOES-NOT-EXIST/register-status",
            json={"status": "RECEIVED"},
        )
        assert r.status_code == 404

    def test_get_review_not_found(self, client):
        r = client.get("/submittals/DOES-NOT-EXIST/review")
        assert r.status_code == 404


# ============================================================
# 2. API — Invalid status transitions
# ============================================================


class TestInvalidStatusTransitions:
    """Verify invalid register status values are rejected."""

    def test_invalid_register_status_value(self, client, db_session):
        _seed_submittal(db_session)
        db_session.commit()
        r = client.patch(
            "/submittals/SUB-001/register-status",
            json={"status": "INVALID_STATUS"},
        )
        assert r.status_code == 422 or r.status_code == 400

    def test_reviewed_with_pending_findings(self, db_session):
        """Cannot mark REVIEWED when findings are unresolved."""
        s = _seed_submittal(db_session)
        _seed_finding(db_session, s.id, status="PENDING_REVIEW")
        db_session.commit()

        with pytest.raises(ValueError, match="unresolved"):
            update_register_status(db_session, s, "REVIEWED")


# ============================================================
# 3. Service — register item validation
# ============================================================


class TestRegisterItemValidation:
    """Verify create_register_item validates inputs."""

    def test_missing_title(self, db_session):
        with pytest.raises(ValueError, match="title"):
            create_register_item(
                db_session,
                "TEST-001",
                {
                    "specification_section": "09 65 00",
                    "source_evidence": "Required per spec",
                },
            )

    def test_empty_title(self, db_session):
        with pytest.raises(ValueError, match="title"):
            create_register_item(
                db_session,
                "TEST-001",
                {
                    "title": "   ",
                    "specification_section": "09 65 00",
                    "source_evidence": "Required per spec",
                },
            )

    def test_missing_specification_section(self, db_session):
        with pytest.raises(ValueError, match="specification_section"):
            create_register_item(
                db_session,
                "TEST-001",
                {
                    "title": "Flooring Data",
                    "source_evidence": "Required per spec",
                },
            )

    def test_missing_source_evidence(self, db_session):
        with pytest.raises(ValueError, match="source_evidence"):
            create_register_item(
                db_session,
                "TEST-001",
                {
                    "title": "Flooring Data",
                    "specification_section": "09 65 00",
                },
            )


# ============================================================
# 4. Service — review_finding validation
# ============================================================


class TestReviewFindingValidation:
    """Verify review_finding rejects invalid inputs."""

    def test_invalid_decision(self, db_session):
        s = _seed_submittal(db_session)
        f = _seed_finding(db_session, s.id)
        db_session.commit()

        with pytest.raises(ValueError, match="decision"):
            review_finding(
                db_session,
                f.id,
                reviewer="Reviewer",
                decision="INVALID_DECISION",
            )

    def test_finding_not_found(self, db_session):
        with pytest.raises(ValueError, match="not found"):
            review_finding(
                db_session,
                "nonexistent-id",
                reviewer="Reviewer",
                decision="APPROVE",
            )

    def test_already_reviewed(self, db_session):
        s = _seed_submittal(db_session)
        f = _seed_finding(db_session, s.id, status="APPROVED")
        db_session.commit()

        with pytest.raises(ValueError, match="already been reviewed"):
            review_finding(
                db_session,
                f.id,
                reviewer="Reviewer",
                decision="APPROVE",
            )


# ============================================================
# 5. Service — update_submittal_status
# ============================================================


class TestUpdateSubmittalStatus:
    """Verify technical status recalculation."""

    def test_no_findings_yields_reviewed(self, db_session):
        s = _seed_submittal(db_session)
        db_session.commit()

        result = update_submittal_status(db_session, s.id)
        assert result.status == "REVIEWED"

    def test_pending_findings_yields_pending_review(self, db_session):
        s = _seed_submittal(db_session)
        _seed_finding(db_session, s.id, status="PENDING_REVIEW")
        db_session.commit()

        result = update_submittal_status(db_session, s.id)
        assert result.status == "PENDING_REVIEW"
        assert result.register_status == "UNDER_REVIEW"

    def test_all_approved_yields_compliant(self, db_session):
        s = _seed_submittal(db_session)
        _seed_finding(db_session, s.id, status="APPROVED")
        db_session.commit()

        result = update_submittal_status(db_session, s.id)
        assert result.status == "REVIEWED_COMPLIANT"
        assert result.register_status == "REVIEWED"

    def test_approved_deviation_yields_deviation(self, db_session):
        s = _seed_submittal(db_session)
        f = _seed_finding(db_session, s.id, status="APPROVED")
        f.result = "DEVIATION"
        db_session.commit()

        result = update_submittal_status(db_session, s.id)
        assert result.status == "REVIEWED_DEVIATION"

    def test_nonexistent_submittal_raises(self, db_session):
        with pytest.raises(ValueError, match="not found"):
            update_submittal_status(db_session, "nonexistent-id")


# ============================================================
# 6. API — generate register endpoint validation
# ============================================================


class TestGenerateRegisterAPI:
    """Verify register generation endpoint."""

    def test_empty_requirements_returns_empty(self, client):
        r = client.post(
            "/projects/TEST-001/submittals/register",
            json={"requirements": []},
        )
        assert r.status_code == 200
        assert r.json()["count"] == 0

    def test_idempotent_register_generation(self, client):
        payload = {
            "requirements": [
                {
                    "title": "Flooring Product Data",
                    "specification_section": "09 65 00",
                    "source_evidence": "Required per spec",
                }
            ]
        }
        r1 = client.post(
            "/projects/TEST-001/submittals/register",
            json=payload,
        )
        assert r1.status_code == 200
        assert r1.json()["count"] == 1
        first_number = r1.json()["items"][0]["number"]

        r2 = client.post(
            "/projects/TEST-001/submittals/register",
            json=payload,
        )
        assert r2.status_code == 200
        assert r2.json()["count"] == 1
        assert r2.json()["items"][0]["number"] == first_number


# ============================================================
# 7. API — SuperDocs error mapping
# ============================================================


class TestSuperDocsErrorMapping:
    """Verify _raise_superdocs_error maps 5xx to 502."""

    def test_raise_superdocs_error_maps_500(self):
        import httpx
        from app.main import _raise_superdocs_error
        from fastapi import HTTPException

        mock_response = httpx.Response(
            status_code=500,
            text="Internal Server Error",
            request=httpx.Request("POST", "http://test"),
        )
        error = httpx.HTTPStatusError(
            message="test",
            request=mock_response.request,
            response=mock_response,
        )

        with pytest.raises(HTTPException) as exc_info:
            _raise_superdocs_error(error)
        assert exc_info.value.status_code == 502

    def test_raise_superdocs_error_preserves_4xx(self):
        import httpx
        from app.main import _raise_superdocs_error
        from fastapi import HTTPException

        mock_response = httpx.Response(
            status_code=422,
            text="Unprocessable Entity",
            request=httpx.Request("POST", "http://test"),
        )
        error = httpx.HTTPStatusError(
            message="test",
            request=mock_response.request,
            response=mock_response,
        )

        with pytest.raises(HTTPException) as exc_info:
            _raise_superdocs_error(error)
        assert exc_info.value.status_code == 422


# ============================================================
# 8. API — health check
# ============================================================


class TestHealthCheck:
    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
