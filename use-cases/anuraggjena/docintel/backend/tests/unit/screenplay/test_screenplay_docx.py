from io import BytesIO
import pytest
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

from backend.core.export.docx_generator import DOCXGenerator


def _item(element_type, text, status="approved", original=None, index=0):
    return {
        "element_type": element_type,
        "formatted_text": text,
        "original_text": original or text,
        "status": status,
        "element_index": index,
    }


def test_generate_screenplay_docx_returns_bytes():
    gen = DOCXGenerator()
    items = [
        _item("title", "LAST CALL", index=0),
        _item("author", "Written by A. Sharma", index=1),
        _item("scene_heading", "INT. DIVE BAR - NIGHT", index=2),
        _item("action", "A worn-out bar in the outskirts of the city.", index=3),
        _item("character", "MEENA", index=4),
        _item("parenthetical", "(without looking up)", index=5),
        _item("dialogue", "You've been sitting there two hours.", index=6),
        _item("transition", "FADE OUT.", index=7),
        _item("end", "END", index=8),
    ]
    result = gen.generate_screenplay_docx(
        formatting_items=items, title="LAST CALL", workspace_name="Screenplay E2E Test"
    )
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_generate_screenplay_docx_no_generic_headers():
    gen = DOCXGenerator()
    items = [
        _item("title", "LAST CALL", index=0),
        _item("author", "Written by A. Sharma", index=1),
        _item("scene_heading", "INT. DIVE BAR - NIGHT", index=2),
    ]
    result = gen.generate_screenplay_docx(
        formatting_items=items, title="Formatted Screenplay", workspace_name="Screenplay E2E Test"
    )
    doc = Document(BytesIO(result))
    all_texts = [p.text for p in doc.paragraphs]

    # Must NOT contain generic document headers or workspace metadata
    assert "Formatted Screenplay" not in all_texts
    assert not any("Workspace:" in t for t in all_texts)
    # Starts directly with title
    assert doc.paragraphs[0].text == "LAST CALL"
    assert doc.paragraphs[1].text == "Written by A. Sharma"
    assert doc.paragraphs[2].text == "INT. DIVE BAR - NIGHT"


def test_generate_screenplay_docx_page_setup_and_margins():
    gen = DOCXGenerator()
    items = [_item("scene_heading", "INT. OFFICE - DAY", index=0)]
    result = gen.generate_screenplay_docx(formatting_items=items)
    doc = Document(BytesIO(result))

    section = doc.sections[0]
    assert abs(section.page_width.inches - 8.5) < 0.01
    assert abs(section.page_height.inches - 11.0) < 0.01
    assert abs(section.left_margin.inches - 1.5) < 0.01
    assert abs(section.right_margin.inches - 1.0) < 0.01
    assert abs(section.top_margin.inches - 1.0) < 0.01
    assert abs(section.bottom_margin.inches - 1.0) < 0.01


def test_generate_screenplay_docx_typography_and_indentation():
    gen = DOCXGenerator()
    items = [
        _item("title", "MY SCRIPT", index=0),
        _item("author", "Written by Jane Doe", index=1),
        _item("scene_heading", "INT. ROOM - DAY", index=2),
        _item("action", "She enters quietly.", index=3),
        _item("character", "JANE", index=4),
        _item("parenthetical", "(whispering)", index=5),
        _item("dialogue", "Is anyone here?", index=6),
        _item("transition", "FADE OUT.", index=7),
        _item("end", "THE END", index=8),
    ]
    result = gen.generate_screenplay_docx(formatting_items=items)
    doc = Document(BytesIO(result))

    paragraphs = doc.paragraphs
    assert len(paragraphs) == 9

    # Title
    p_title = paragraphs[0]
    assert p_title.text == "MY SCRIPT"
    assert p_title.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert p_title.runs[0].bold is True
    assert p_title.runs[0].font.name == "Courier New"

    # Author
    p_author = paragraphs[1]
    assert p_author.text == "Written by Jane Doe"
    assert p_author.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert p_author.runs[0].font.name == "Courier New"

    # Scene heading
    p_scene = paragraphs[2]
    assert p_scene.text == "INT. ROOM - DAY"
    assert p_scene.alignment == WD_ALIGN_PARAGRAPH.LEFT
    assert p_scene.runs[0].bold is True
    assert p_scene.paragraph_format.keep_with_next is True

    # Action
    p_action = paragraphs[3]
    assert p_action.text == "She enters quietly."
    assert p_action.alignment == WD_ALIGN_PARAGRAPH.LEFT

    # Character cue (2.0" left indent, uppercase bold, keep_with_next)
    p_char = paragraphs[4]
    assert p_char.text == "JANE"
    assert abs(p_char.paragraph_format.left_indent.inches - 2.0) < 0.01
    assert p_char.runs[0].bold is True
    assert p_char.paragraph_format.keep_with_next is True

    # Parenthetical (1.5" left indent, 2.0" right indent, keep_with_next)
    p_paren = paragraphs[5]
    assert p_paren.text == "(whispering)"
    assert abs(p_paren.paragraph_format.left_indent.inches - 1.5) < 0.01
    assert abs(p_paren.paragraph_format.right_indent.inches - 2.0) < 0.01
    assert p_paren.paragraph_format.keep_with_next is True

    # Dialogue (1.0" left indent, 1.5" right indent)
    p_diag = paragraphs[6]
    assert p_diag.text == "Is anyone here?"
    assert abs(p_diag.paragraph_format.left_indent.inches - 1.0) < 0.01
    assert abs(p_diag.paragraph_format.right_indent.inches - 1.5) < 0.01

    # Transition (right aligned, bold)
    p_trans = paragraphs[7]
    assert p_trans.text == "FADE OUT."
    assert p_trans.alignment == WD_ALIGN_PARAGRAPH.RIGHT
    assert p_trans.runs[0].bold is True

    # End (centered, bold)
    p_end = paragraphs[8]
    assert p_end.text == "THE END"
    assert p_end.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert p_end.runs[0].bold is True


def test_generate_screenplay_docx_uses_original_for_rejected():
    gen = DOCXGenerator()
    items = [
        _item("scene_heading", "INT. CAFE - DAY", status="rejected", original="int. cafe - day"),
    ]
    result = gen.generate_screenplay_docx(formatting_items=items)
    doc = Document(BytesIO(result))
    assert doc.paragraphs[0].text == "int. cafe - day"


def test_generate_screenplay_docx_empty_items():
    gen = DOCXGenerator()
    result = gen.generate_screenplay_docx(formatting_items=[], title="Empty", workspace_name="WS")
    assert isinstance(result, bytes)
    assert len(result) > 0
