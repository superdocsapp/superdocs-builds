"""Tests for the DocDiffer engine."""

from build_a.differ import ChangeType, DocDiffer


def test_basic_diff(sample_pre_edit_html: str, sample_post_edit_html: str) -> None:
    differ = DocDiffer()
    result = differ.diff(sample_pre_edit_html, sample_post_edit_html)

    assert result.has_changes
    assert len(result.changed) == 2  # one modified, one added
    assert result.total_paragraphs_old == 3
    assert result.total_paragraphs_new == 4


def test_modified_paragraph(sample_pre_edit_html: str, sample_post_edit_html: str) -> None:
    differ = DocDiffer()
    result = differ.diff(sample_pre_edit_html, sample_post_edit_html)

    modified = [d for d in result.changed if d.change_type == ChangeType.MODIFIED]
    assert len(modified) == 1
    assert "second paragraph" in modified[0].old_text.lower()
    assert "modified" in modified[0].new_text.lower()


def test_added_paragraph(sample_pre_edit_html: str, sample_post_edit_html: str) -> None:
    differ = DocDiffer()
    result = differ.diff(sample_pre_edit_html, sample_post_edit_html)

    added = [d for d in result.changed if d.change_type == ChangeType.ADDED]
    assert len(added) == 1
    assert "new paragraph" in added[0].new_text.lower()


def test_no_changes() -> None:
    html = "<html><body><p>Hello world.</p></body></html>"
    differ = DocDiffer()
    result = differ.diff(html, html)
    assert not result.has_changes
    assert len(result.changed) == 0


def test_empty_documents() -> None:
    differ = DocDiffer()
    result = differ.diff("<html><body></body></html>", "<html><body></body></html>")
    assert not result.has_changes
    assert result.total_paragraphs_old == 0
    assert result.total_paragraphs_new == 0


def test_all_removed() -> None:
    pre = "<html><body><p>Paragraph A</p><p>Paragraph B</p></body></html>"
    post = "<html><body></body></html>"
    differ = DocDiffer()
    result = differ.diff(pre, post)
    assert result.has_changes
    assert all(d.change_type == ChangeType.REMOVED for d in result.changed)
    assert len(result.changed) == 2


def test_instruction_payload_format(sample_pre_edit_html: str, sample_post_edit_html: str) -> None:
    differ = DocDiffer()
    result = differ.diff(sample_pre_edit_html, sample_post_edit_html)
    payload = result.to_instruction_payload()
    assert "Paragraph" in payload
    assert "[~]" in payload or "[+]" in payload


def test_from_chunk_diffs() -> None:
    chunk_diffs = [
        {"chunk_id": "c1", "old_text": "Hello", "new_text": "Hello world"},
        {"chunk_id": "c2", "old_text": "", "new_text": "New content"},
    ]
    differ = DocDiffer()
    result = differ.from_chunk_diffs(chunk_diffs)
    assert result.has_changes
    assert len(result.changed) == 2


def test_from_chunk_diffs_all_unchanged() -> None:
    chunk_diffs = [
        {"chunk_id": "c1", "old_text": "Hello", "new_text": "Hello"},
        {"chunk_id": "c2", "old_text": "World", "new_text": "World"},
    ]
    differ = DocDiffer()
    result = differ.from_chunk_diffs(chunk_diffs)
    assert not result.has_changes


def test_empty_html_both_sides() -> None:
    differ = DocDiffer()
    result = differ.diff("<html><body></body></html>", "<html><body></body></html>")
    assert not result.has_changes
    assert result.total_paragraphs_old == 0
    assert result.total_paragraphs_new == 0


def test_formatting_only_changes() -> None:
    pre = '<html><body><p class="old">Hello world</p></body></html>'
    post = '<html><body><p class="new">Hello world</p></body></html>'
    differ = DocDiffer()
    result = differ.diff(pre, post)
    assert not result.has_changes  # text is identical


def test_div_wrapped_content() -> None:
    pre = '<html><body><div><p>Paragraph inside div</p></div></body></html>'
    post = '<html><body><div><p>Modified paragraph inside div</p></div></body></html>'
    differ = DocDiffer()
    result = differ.diff(pre, post)
    assert result.has_changes


def test_nested_lists() -> None:
    pre = '<html><body><ul><li>Item A</li><li>Item B</li></ul></body></html>'
    post = '<html><body><ul><li>Item A</li><li>Item B modified</li></ul></body></html>'
    differ = DocDiffer()
    result = differ.diff(pre, post)
    assert result.has_changes
    assert len(result.changed) == 1
