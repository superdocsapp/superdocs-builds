from pathlib import Path

from docx import Document as WordDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from src.adapters.docx import parse_docx
from src.fingerprint import fingerprint


def test_identical_docx_has_same_fingerprint(tmp_path):
    path = tmp_path / "resume.docx"

    create_test_docx(path)

    document1 = parse_docx(path)
    document2 = parse_docx(path)

    assert fingerprint(document1) == fingerprint(document2)


def test_docx_paragraph_removal_changes_fingerprint(tmp_path):
    original_path = tmp_path / "original.docx"
    changed_path = tmp_path / "changed.docx"

    create_test_docx(original_path)

    original = WordDocument(original_path)

    # Remove the second paragraph.
    paragraph = original.paragraphs[1]
    paragraph._element.getparent().remove(
        paragraph._element
    )

    original.save(changed_path)

    before = parse_docx(original_path)
    after = parse_docx(changed_path)

    assert fingerprint(before) != fingerprint(after)


def test_docx_heading_style_change_changes_fingerprint(tmp_path):
    original_path = tmp_path / "original.docx"
    changed_path = tmp_path / "changed.docx"

    create_test_docx(original_path)

    original = WordDocument(original_path)

    original.paragraphs[0].style = "Heading 2"
    original.save(changed_path)

    before = parse_docx(original_path)
    after = parse_docx(changed_path)

    assert fingerprint(before) != fingerprint(after)


def test_docx_table_structure_change_changes_fingerprint(tmp_path):
    original_path = tmp_path / "original.docx"
    changed_path = tmp_path / "changed.docx"

    create_test_docx(original_path)

    original = WordDocument(original_path)

    table = original.tables[0]

    # Remove the second column from the first row.
    row = table.rows[0]
    cell = row.cells[1]
    cell._tc.getparent().remove(cell._tc)

    original.save(changed_path)

    before = parse_docx(original_path)
    after = parse_docx(changed_path)

    assert fingerprint(before) != fingerprint(after)


def test_docx_run_formatting_change_changes_fingerprint(tmp_path):
    original_path = tmp_path / "original.docx"
    changed_path = tmp_path / "changed.docx"

    create_test_docx(original_path)

    original = WordDocument(original_path)

    run = original.paragraphs[0].runs[0]
    run.bold = False

    original.save(changed_path)

    before = parse_docx(original_path)
    after = parse_docx(changed_path)

    assert fingerprint(before) != fingerprint(after)


def create_test_docx(path: Path) -> None:
    document = WordDocument()

    heading = document.add_paragraph()
    heading.style = "Heading 1"

    run = heading.add_run("John Doe")
    run.bold = True
    run.font.name = "Arial"
    run.font.size = Pt(18)

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    run = paragraph.add_run("Software Engineer")
    run.italic = True

    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Skill"
    table.cell(0, 1).text = "Level"
    table.cell(1, 0).text = "Python"
    table.cell(1, 1).text = "Advanced"

    document.save(path)


def test_parse_basic_docx(tmp_path):
    path = tmp_path / "resume.docx"

    create_test_docx(path)

    document = parse_docx(path)

    assert document.source_format == "docx"
    assert document.raw_content is not None
    assert len(document.raw_content) > 0


def test_docx_paragraphs_are_detected(tmp_path):
    path = tmp_path / "resume.docx"

    create_test_docx(path)

    document = parse_docx(path)

    paragraphs = [
        element
        for element in document.elements
        if element.element_type == "paragraph"
    ]

    assert len(paragraphs) == 2
    assert paragraphs[0].text == "John Doe"
    assert paragraphs[1].text == "Software Engineer"


def test_docx_heading_style_is_detected(tmp_path):
    path = tmp_path / "resume.docx"

    create_test_docx(path)

    document = parse_docx(path)

    heading = document.elements[0]

    assert heading.element_type == "paragraph"
    assert heading.formatting["heading_style"] == "Heading 1"


def test_docx_run_formatting_is_detected(tmp_path):
    path = tmp_path / "resume.docx"

    create_test_docx(path)

    document = parse_docx(path)

    heading = document.elements[0]

    runs = heading.formatting["runs"]

    assert len(runs) == 1
    assert runs[0]["text"] == "John Doe"
    assert runs[0]["formatting"]["bold"] is True
    assert runs[0]["formatting"]["font_name"] == "Arial"


def test_docx_italic_formatting_is_detected(tmp_path):
    path = tmp_path / "resume.docx"

    create_test_docx(path)

    document = parse_docx(path)

    paragraph = document.elements[1]

    runs = paragraph.formatting["runs"]

    assert runs[0]["formatting"]["italic"] is True


def test_docx_alignment_is_detected(tmp_path):
    path = tmp_path / "resume.docx"

    create_test_docx(path)

    document = parse_docx(path)

    paragraph = document.elements[1]

    assert paragraph.formatting["alignment"] is not None


def test_docx_table_is_detected(tmp_path):
    path = tmp_path / "resume.docx"

    create_test_docx(path)

    document = parse_docx(path)

    tables = [
        element
        for element in document.elements
        if element.element_type == "table"
    ]

    assert len(tables) == 1

    table = tables[0]

    assert table.formatting["row_count"] == 2
    assert table.formatting["column_counts"] == [2, 2]


def test_docx_table_content_is_preserved(tmp_path):
    path = tmp_path / "resume.docx"

    create_test_docx(path)

    document = parse_docx(path)

    table = [
        element
        for element in document.elements
        if element.element_type == "table"
    ][0]

    assert table.formatting["rows"] == [
        ["Skill", "Level"],
        ["Python", "Advanced"],
    ]


def test_docx_package_hash_exists(tmp_path):
    path = tmp_path / "resume.docx"

    create_test_docx(path)

    document = parse_docx(path)

    package_hash = document.metadata["package_sha256"]

    assert len(package_hash) == 64
    assert all(
        character in "0123456789abcdef"
        for character in package_hash
    )


def test_docx_section_information_is_detected(tmp_path):
    path = tmp_path / "resume.docx"

    create_test_docx(path)

    document = parse_docx(path)

    assert document.metadata["section_count"] == 1
    assert len(document.metadata["sections"]) == 1


def test_invalid_docx_extension_is_rejected(tmp_path):
    path = tmp_path / "resume.txt"
    path.write_text("not a docx")

    try:
        parse_docx(path)
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert "Expected a .docx file" in str(exc)


def test_missing_docx_is_rejected(tmp_path):
    path = tmp_path / "missing.docx"

    try:
        parse_docx(path)
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError:
        pass
