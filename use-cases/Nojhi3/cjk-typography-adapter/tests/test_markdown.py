from adapter.markdown import md_to_html


def test_headings_and_paragraph():
    html = md_to_html("# Title\n\nHello world.")
    assert "<h1>Title</h1>" in html
    assert "<p>Hello world.</p>" in html


def test_bold_italic_code_link():
    html = md_to_html("**bold** and *em* and `code` and [link](https://example.com)")
    assert "<strong>bold</strong>" in html
    assert "<em>em</em>" in html
    assert "<code>code</code>" in html
    assert '<a href="https://example.com">link</a>' in html


def test_list():
    html = md_to_html("- one\n- two\n- three")
    assert "<ul>" in html
    assert html.count("<li>") == 3


def test_table():
    html = md_to_html("| A | B |\n| --- | --- |\n| 1 | 2 |")
    assert "<table>" in html
    assert "<th>A</th>" in html
    assert "<td>1</td>" in html


def test_blockquote_and_hr():
    html = md_to_html("> quoted text\n\n---")
    assert "<blockquote>quoted text</blockquote>" in html
    assert "<hr>" in html


def test_code_fence():
    html = md_to_html("```\n1, 2, 3.\n```")
    assert "<pre>1, 2, 3.</pre>" in html


def test_special_chars_escaped():
    html = md_to_html("a & b < c")
    assert "a &amp; b &lt; c" in html
