from io import BytesIO

from docx import Document

from core.docx_render import markdown_to_docx_bytes


def _open_docx(markdown: str) -> Document:
    return Document(
        BytesIO(
            markdown_to_docx_bytes(
                markdown
            )
        )
    )


def test_summary_markdown_is_rendered_not_printed():
    document = _open_docx(
        "\n".join(
            [
                "## Reconciliation Summary",
                "- Matching fields: **5**",
                "- Tolerable variances: **1**",
                "- Curable variances: **2**",
                "- Unresolved findings: **0**",
                "",
                "**Funding review is required.**",
            ]
        )
    )

    visible_text = "\n".join(
        paragraph.text
        for paragraph in document.paragraphs
    )

    assert "**" not in visible_text
    assert "Matching fields: 5" in visible_text
    assert "Tolerable variances: 1" in visible_text
    assert "Curable variances: 2" in visible_text
    assert "Unresolved findings: 0" in visible_text
    assert "Funding review is required." in visible_text


def test_bold_runs_are_preserved():
    document = _open_docx(
        "- Matching fields: **5**"
    )

    paragraph = document.paragraphs[0]

    bold_runs = [
        run.text
        for run in paragraph.runs
        if run.bold
    ]

    assert bold_runs == ["5"]


def test_source_value_marker_becomes_italics():
    document = _open_docx(
        (
            "**closing_disclosure.docx:** 420,000 "
            "_(source value: $420,000.00)_"
        )
    )

    paragraph = document.paragraphs[0]

    assert "**" not in paragraph.text
    assert "_(" not in paragraph.text
    assert ")_" not in paragraph.text

    assert any(
        run.bold
        and run.text
        == "closing_disclosure.docx:"
        for run in paragraph.runs
    )

    assert any(
        run.italic
        and run.text
        == "(source value: $420,000.00)"
        for run in paragraph.runs
    )
