from backend.models.memo_section import MemoSection


def test_memo_section_tablename():
    assert MemoSection.__tablename__ == "memo_sections"


def test_memo_section_has_required_columns():
    columns = {c.name for c in MemoSection.__table__.columns}
    required = {
        "id",
        "workflow_run_id",
        "section_type",
        "title",
        "section_order",
        "content",
        "status",
        "source_attribution",
        "analyst_reasoning",
        "evidence_refs",
        "confidence",
        "baseline_section_id",
        "structured_data",
        "created_at",
        "updated_at",
    }
    assert required.issubset(columns)
