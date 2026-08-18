from backend.html_renderer import render_press_kit_html


def test_html_escapes_untrusted_text():
    kit = {
        "title": "A <Game>",
        "fact_sheet": {"studio": "S & Co", "release_date": "Now", "platforms": ["PC"], "price": "$1", "availability": "Digital"},
        "descriptions": {"one_line": "<script>x</script>", "one_paragraph": "P", "long_form": "L"},
        "features": ["<b>feature</b>"],
        "history_and_inspiration": {"history": "H", "inspiration": "I"},
        "quote": {"text": 'Say "hi"', "attribution": "A"},
        "awards": [{"name": "Award", "year": 2026}],
        "coverage": [{"publication": "Pub", "headline": "Headline", "url": "https://example.com"}],
        "asset_index": [{"filename": "a.jpg", "type": "screenshot", "caption": "C", "credit": "D"}],
    }
    html = render_press_kit_html(kit)
    assert "&lt;script&gt;x&lt;/script&gt;" in html
    assert "<script>x</script>" not in html
    assert "S &amp; Co" in html
