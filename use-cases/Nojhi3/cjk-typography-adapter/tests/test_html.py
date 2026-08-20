from adapter.htmltree import (
    apply_html_structure,
    apply_text_rules_to_tree,
    collect_blocks,
    find_title,
    parse_html,
    serialize,
)
from adapter.profile import load_profile
from adapter.text import _new_stats

JA = load_profile("ja")


def test_lang_and_style_injected():
    tree = parse_html("<html><body><p>Hello.</p></body></html>")
    apply_html_structure(tree, JA)
    out = serialize(tree)
    assert 'lang="ja"' in out
    assert "@page" in out
    assert "size: 210mm 297mm" in out
    assert "margin: 25mm 20mm 25mm 20mm" in out
    assert "line-break: strict" in out
    assert "font-size: 10.5pt" in out


def test_text_rules_applied_to_paragraphs():
    tree = parse_html("<body><p>Budget review on Tuesday.</p></body>")
    stats = _new_stats()
    apply_text_rules_to_tree(tree, JA, stats)
    assert "Tuesday。" in serialize(tree)
    assert stats["punctuation"]["count"] == 1


def test_pre_and_code_untouched():
    tree = parse_html(
        "<body><p>Hello.</p><pre>1, 2, 3. done.</pre><code>x = y.</code></body>"
    )
    stats = _new_stats()
    apply_text_rules_to_tree(tree, JA, stats)
    out = serialize(tree)
    assert "1, 2, 3. done." in out
    assert "x = y." in out
    assert stats["punctuation"]["count"] == 1


def test_entity_round_trip():
    tree = parse_html("<p>Northwind Corp &amp; Pacific</p>")
    assert serialize(tree) == "<html><p>Northwind Corp &amp; Pacific</p></html>"


def test_title_detection():
    tree = parse_html("<head><title>My Doc</title></head><body><p>Hi.</p></body>")
    assert find_title(tree) == "My Doc"


def test_collect_blocks():
    tree = parse_html(
        "<body><h1>Title</h1><p>One. Two.</p><ul><li>Item</li></ul><table><tr><td>Cell</td></tr></table></body>"
    )
    assert collect_blocks(tree) == ["Title", "One. Two.", "Item", "Cell"]


def test_serialize_escaping():
    tree = parse_html('<p title="a &amp; b">x &lt; y</p>')
    assert serialize(tree) == '<html><p title="a &amp; b">x &lt; y</p></html>'


def test_doctype_preserved():
    tree = parse_html("<!DOCTYPE html><html><body><p>Hi.</p></body></html>")
    assert serialize(tree).startswith("<!DOCTYPE html>")


def test_fragment_gets_lang():
    tree = parse_html("<p>Just a paragraph.</p>")
    apply_html_structure(tree, JA)
    assert 'lang="ja"' in serialize(tree)
