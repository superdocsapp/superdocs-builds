"""FastAPI TestClient integration tests across all mounted routes (Build A, B, and C)."""

from fastapi.testclient import TestClient
import pytest

from server import app

client = TestClient(app)


def test_server_health_check():
    """Verify health endpoint lists all 3 builds."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert len(data["builds"]) == 3


def test_build_c_generate_study_guide_endpoint():
    """Verify POST /api/study-guide/generate returns structured Cornell notes with LaTeX."""
    payload = {
        "subject": "Quantum Physics",
        "topic": "Schrodinger Equation & Wavefunctions",
        "target_exam": "University Physics",
        "raw_notes": "i hbar d/dt Psi = H Psi, H = -hbar^2/2m del^2 + V",
        "depth": "detailed",
    }
    res = client.post("/api/study-guide/generate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "session_id" in data
    assert "guide_markdown" in data
    assert "Quick Reference" in data["guide_markdown"]
    assert "Cornell Conceptual Breakdown" in data["guide_markdown"]


def test_build_c_chat_refine_endpoint():
    """Verify POST /api/study-guide/chat applies conversational modifications."""
    payload = {
        "session_id": "test_integration_sess",
        "current_markdown": "# Title\n\n## 1. Quick Reference\nFormula.",
        "instruction": "Derive the probability current density j",
    }
    res = client.post("/api/study-guide/chat", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "updated_markdown" in data
    assert "Revision Note" in data["updated_markdown"]


def test_build_c_export_pdf_endpoint():
    """Verify POST /api/study-guide/export compiles vector PDF and stamps headers."""
    payload = {
        "subject": "Quantum Physics",
        "topic": "Schrodinger Equation",
        "guide_markdown": "# Schrodinger Equation\n\n## 1. Quick Reference\n$$\\hat{H}\\Psi = E\\Psi$$",
    }
    res = client.post("/api/study-guide/export", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["page_count"] >= 1
    assert data["pdf_base64"].startswith("JVBERi0")
    assert "STUDY GUIDE: QUANTUM PHYSICS" in data["stamped_header"]


def test_build_a_diff_endpoint():
    """Verify POST /api/diff computes semantic difference."""
    payload = {
        "old_html": "<h2>Section 1</h2><p>Original text</p>",
        "new_html": "<h2>Section 1</h2><p>Revised text</p>",
    }
    res = client.post("/api/diff", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "total_changes" in data
    assert data["total_changes"] >= 1
