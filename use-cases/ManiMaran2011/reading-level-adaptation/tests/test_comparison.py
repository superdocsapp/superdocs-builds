from src.adaptation import run_adaptation
from src.chunk_classifier import protected_ids
from src.comparison import build_comparison, render_html
from src.fake_client import FakeSuperDocsClient, default_simplify_transform
from tests.fixtures import SAMPLE_CHAPTER_HTML


def test_comparison_rows_align_by_chunk_id_and_flag_protected_status():
    client = FakeSuperDocsClient()
    protected = set(protected_ids(SAMPLE_CHAPTER_HTML))
    client.script_edit("Rewrite the prose", default_simplify_transform(protected))

    result = run_adaptation(client, "source-1", SAMPLE_CHAPTER_HTML, "lower_reading_level")
    rows = build_comparison(SAMPLE_CHAPTER_HTML, {"lower_reading_level": result})

    row_by_id = {r.chunk_id: r for r in rows}
    assert row_by_id["c2"].kind == "prose"
    assert "[simplified]" in row_by_id["c2"].adapted_text["lower_reading_level"]

    assert row_by_id["c7"].kind == "protected"
    assert row_by_id["c7"].unchanged_confirmed is True
    assert row_by_id["c7"].adapted_text["lower_reading_level"] == row_by_id["c7"].source_text

    html = render_html(rows, ["lower_reading_level"])
    assert "✅ unchanged" in html
    assert "❌" not in html  # nothing should be flagged as broken in the well-behaved case
