from soc2_index.superdocs.render_live import fill_prompt


def test_fill_prompt_snapshot():
    msg = fill_prompt(index_id="doc_index", listed_name="SOC2-Evidence-Index", compact_json="[]")
    assert "document_id=doc_index" in msg
    assert 'template named "SOC2-Evidence-Index"' in msg
    assert "Do not drop GAP rows" in msg
    assert "Do not invent evidence" in msg
    assert "data-row-id=" in msg
    assert "JSON array:" in msg
