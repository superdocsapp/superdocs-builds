from backend.models.lineage import LineageLink


def test_lineage_link_import():
    """Test that LineageLink model can be imported"""
    assert LineageLink is not None


def test_lineage_link_has_required_columns():
    """Test that LineageLink has all required columns"""
    cols = {c.name for c in LineageLink.__table__.columns}

    # From UUIDMixin
    assert "id" in cols

    # From TimestampMixin
    assert "created_at" in cols
    assert "updated_at" in cols

    # Source entity
    assert "source_type" in cols
    assert "source_id" in cols

    # Target entity
    assert "target_type" in cols
    assert "target_id" in cols

    # Relationship semantics
    assert "link_type" in cols

    # Context
    assert "workflow_run_id" in cols
    assert "stage_name" in cols

    # Additional metadata
    assert "metadata" in cols


def test_lineage_link_indexes():
    """Test that LineageLink has all required indexes"""
    indexes = {idx.name for idx in LineageLink.__table__.indexes}

    assert "ix_lineage_links_source" in indexes
    assert "ix_lineage_links_target" in indexes
    assert "ix_lineage_links_run" in indexes
    assert "ix_lineage_links_type" in indexes
    assert "ix_lineage_links_run_type" in indexes


def test_lineage_link_unique_constraint():
    """Test that LineageLink has unique constraint to prevent duplicate edges"""
    constraints = {c.name for c in LineageLink.__table__.constraints if hasattr(c, 'name')}
    assert "uq_lineage_link" in constraints
