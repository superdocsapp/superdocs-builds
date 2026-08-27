from series_bible.application.ingestion import IngestionService


def test_superdocs_html_is_normalized_into_semantic_blocks():
    html = "<h1>Chapter 6</h1><p>Elena has green eyes.</p><script>ignore()</script>"
    assert IngestionService._html_to_text(html) == "Chapter 6\n\nElena has green eyes."


def test_nested_superdocs_response_html_is_discovered():
    response = {"document": {"document_html": "<p>Grounded text</p>"}}
    assert IngestionService._find_html(response) == "<p>Grounded text</p>"