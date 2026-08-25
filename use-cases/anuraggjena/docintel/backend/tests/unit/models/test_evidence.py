def test_evidence_model_importable():
    from backend.models.evidence import Evidence, Citation
    assert Evidence.__tablename__ == "evidence"
    assert Citation.__tablename__ == "citations"


def test_evidence_has_required_columns():
    from backend.models.evidence import Evidence
    cols = {c.name for c in Evidence.__table__.columns}
    assert "id" in cols
    assert "workflow_run_id" in cols
    assert "document_id" in cols
    assert "chunk_id" in cols
    assert "extracted_text" in cols
    assert "evidence_type" in cols
    assert "relevance_score" in cols


def test_citation_has_required_columns():
    from backend.models.evidence import Citation
    cols = {c.name for c in Citation.__table__.columns}
    assert "id" in cols
    assert "claim_id" in cols
    assert "evidence_id" in cols
    assert "excerpt" in cols
    assert "relevance_score" in cols
