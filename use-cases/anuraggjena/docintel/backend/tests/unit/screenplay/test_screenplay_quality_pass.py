import io
import pytest
from docx import Document
from pypdf import PdfReader

from backend.modules.screenplay.formatter import format_element
from backend.modules.screenplay.parser import ScreenplayParser
from backend.modules.screenplay.validator import ContentDriftValidator
from backend.core.export.docx_generator import DOCXGenerator
from backend.core.export.pdf_generator import PDFGenerator


# ==============================================================================
# 1. Parenthetical Formatting & Proper Name Preservation
# ==============================================================================

def test_parenthetical_proper_names_preserved():
    """Verify that proper character names are NOT lowercased."""
    cases = [
        ("(to Dana, low)", "(to Dana, low)", "no_change"),
        ("(to Raines)", "(to Raines)", "no_change"),
        ("(to Vasquez, urgent)", "(to Vasquez, urgent)", "no_change"),
        ("(whispering to Sarah)", "(whispering to Sarah)", "no_change"),
        ("(pointing to Brooklyn)", "(pointing to Brooklyn)", "no_change"),
    ]
    for raw, expected_text, expected_change in cases:
        formatted_text, change_type, _ = format_element("parenthetical", raw)
        assert formatted_text == expected_text
        assert change_type == expected_change


def test_parenthetical_acronyms_preserved():
    """Verify that standard audio/screenplay acronyms are preserved verbatim."""
    cases = [
        ("(V.O.)", "(V.O.)", "no_change"),
        ("(O.S.)", "(O.S.)", "no_change"),
        ("(M.O.S.)", "(M.O.S.)", "no_change"),
        ("(CONT'D)", "(CONT'D)", "no_change"),
    ]
    for raw, expected_text, expected_change in cases:
        formatted_text, change_type, _ = format_element("parenthetical", raw)
        assert formatted_text == expected_text
        assert change_type == expected_change


def test_parenthetical_standard_directions():
    """Verify standard parenthetical directions."""
    cases = [
        ("(whispering)", "(whispering)", "no_change"),
        ("(beat)", "(beat)", "no_change"),
        ("(into phone)", "(into phone)", "no_change"),
        ("(42)", "(42)", "no_change"),
        ("(beat, then smiles)", "(beat, then smiles)", "no_change"),
    ]
    for raw, expected_text, expected_change in cases:
        formatted_text, change_type, _ = format_element("parenthetical", raw)
        assert formatted_text == expected_text
        assert change_type == expected_change


def test_parenthetical_missing_parentheses_corrected():
    """Verify parentheticals missing parens generate genuine formatting proposal."""
    formatted_text, change_type, reason = format_element("parenthetical", "to Dana, low")
    assert formatted_text == "(to Dana, low)"
    assert change_type == "spacing"
    assert "enclosed" in reason.lower()

    formatted_text, change_type, reason = format_element("parenthetical", "whispering)")
    assert formatted_text == "(whispering)"
    assert change_type == "spacing"


def test_parenthetical_spacing_normalized():
    """Verify extra whitespace inside parenthetical is cleaned."""
    formatted_text, change_type, reason = format_element("parenthetical", "(   to Dana, low   )")
    assert formatted_text == "(to Dana, low)"
    assert change_type == "spacing"


def test_content_drift_validator_protects_parentheticals():
    """Verify validator protects parentheticals from word drift."""
    validator = ContentDriftValidator()
    # No drift with casing or punctuation
    assert not validator.has_drift("(to Dana, low)", "(to Dana, low)", "parenthetical")
    # Drift if words are changed or added
    assert validator.has_drift("(to Dana, low)", "(to Raines, low)", "parenthetical")


# ==============================================================================
# 2. Element Classification and Formatting Audit
# ==============================================================================

def test_screenplay_element_formatting_rules():
    """Audit all element types for correct formatting and no-change rules."""
    # Scene Heading
    fmt, chg, _ = format_element("scene_heading", "int. cafe - day")
    assert fmt == "INT. CAFE - DAY" and chg == "capitalization"
    fmt, chg, _ = format_element("scene_heading", "INT. CAFE - DAY")
    assert fmt == "INT. CAFE - DAY" and chg == "no_change"

    # Character
    fmt, chg, _ = format_element("character", "dana")
    assert fmt == "DANA" and chg == "capitalization"
    fmt, chg, _ = format_element("character", "DANA (V.O.)")
    assert fmt == "DANA (V.O.)" and chg == "no_change"

    # Transition
    fmt, chg, _ = format_element("transition", "cut to")
    assert fmt == "CUT TO:" and chg == "capitalization"
    fmt, chg, _ = format_element("transition", "FADE OUT.")
    assert fmt == "FADE OUT." and chg == "no_change"

    # Shot
    fmt, chg, _ = format_element("shot", "close up - dana")
    assert fmt == "CLOSE UP - DANA" and chg == "capitalization"
    fmt, chg, _ = format_element("shot", "WIDE SHOT")
    assert fmt == "WIDE SHOT" and chg == "no_change"

    # End
    fmt, chg, _ = format_element("end", "the end")
    assert fmt == "THE END" and chg == "capitalization"
    fmt, chg, _ = format_element("end", "THE END")
    assert fmt == "THE END" and chg == "no_change"

    # Preserved exactly without formatting change
    for elem_type, text in [
        ("title", "UNTITLED SCREENPLAY"),
        ("author", "Written by Anonymous"),
        ("action", "The rain pours heavily against the glass."),
        ("dialogue", "We have to leave before they find us."),
        ("page_number", "12."),
        ("uncertain", "Some ambiguous text"),
    ]:
        fmt, chg, _ = format_element(elem_type, text)
        assert fmt == text
        assert chg == "no_change"


# ==============================================================================
# 3. DOCX Pagination, Spacing, and Keep-With-Next Rules
# ==============================================================================

def test_docx_pagination_and_keep_with_next():
    """Verify DOCX paragraph formatting rules for screenplay typography."""
    gen = DOCXGenerator()
    items = [
        {"element_index": 0, "element_type": "title", "formatted_text": "TITLE", "status": "approved"},
        {"element_index": 1, "element_type": "author", "formatted_text": "By Author", "status": "approved"},
        {"element_index": 2, "element_type": "scene_heading", "formatted_text": "INT. ROOM - DAY", "status": "approved"},
        {"element_index": 3, "element_type": "action", "formatted_text": "Short action.", "status": "approved"},
        {"element_index": 4, "element_type": "character", "formatted_text": "ALICE", "status": "approved"},
        {"element_index": 5, "element_type": "parenthetical", "formatted_text": "(to Bob)", "status": "approved"},
        {"element_index": 6, "element_type": "dialogue", "formatted_text": "Line one.", "status": "approved"},
        {"element_index": 7, "element_type": "parenthetical", "formatted_text": "(pause)", "status": "approved"},
        {"element_index": 8, "element_type": "dialogue", "formatted_text": "Line two.", "status": "approved"},
        {"element_index": 9, "element_type": "shot", "formatted_text": "CLOSE UP", "status": "approved"},
        {"element_index": 10, "element_type": "transition", "formatted_text": "CUT TO:", "status": "approved"},
        {"element_index": 11, "element_type": "end", "formatted_text": "THE END", "status": "approved"},
    ]

    docx_bytes = gen.generate_screenplay_docx(items)
    doc = Document(io.BytesIO(docx_bytes))
    paragraphs = doc.paragraphs

    # Scene heading (index 2) -> keep_with_next = True
    p_scene = paragraphs[2]
    assert p_scene.paragraph_format.keep_with_next is True
    assert p_scene.paragraph_format.space_before.pt == 18
    assert p_scene.paragraph_format.space_after.pt == 12

    # Character cue (index 4) -> keep_with_next = True, space_after = 0
    p_char = paragraphs[4]
    assert p_char.paragraph_format.keep_with_next is True
    assert p_char.paragraph_format.space_before.pt == 0
    assert p_char.paragraph_format.space_after.pt == 0

    # Parenthetical (index 5) -> keep_with_next = True, space_after = 0
    p_paren = paragraphs[5]
    assert p_paren.paragraph_format.keep_with_next is True
    assert p_paren.paragraph_format.space_before.pt == 0
    assert p_paren.paragraph_format.space_after.pt == 0

    # Dialogue continuing to paren (index 6) -> space_after = 0
    p_diag1 = paragraphs[6]
    assert p_diag1.paragraph_format.space_before.pt == 0
    assert p_diag1.paragraph_format.space_after.pt == 0

    # Dialogue ending speech (index 8) -> space_after = 12
    p_diag2 = paragraphs[8]
    assert p_diag2.paragraph_format.space_after.pt == 12

    # Shot (index 9) -> keep_with_next = True
    p_shot = paragraphs[9]
    assert p_shot.paragraph_format.keep_with_next is True

    # Transition (index 10) -> keep_together = True
    p_trans = paragraphs[10]
    assert p_trans.paragraph_format.keep_together is True


def test_dialogue_block_tightness_and_grouping():
    """Verify tight vertical spacing within character/parenthetical/dialogue blocks."""
    gen = DOCXGenerator()
    items = [
        # Scene 1: Character without parenthetical -> Dialogue
        {"element_index": 0, "element_type": "scene_heading", "formatted_text": "INT. ROOM - NIGHT", "status": "approved"},
        {"element_index": 1, "element_type": "action", "formatted_text": "Silence.", "status": "approved"},
        {"element_index": 2, "element_type": "character", "formatted_text": "ALICE", "status": "approved"},
        {"element_index": 3, "element_type": "dialogue", "formatted_text": "Direct dialogue.", "status": "approved"},
        # Multiple dialogue paragraphs from same character
        {"element_index": 4, "element_type": "character", "formatted_text": "BOB", "status": "approved"},
        {"element_index": 5, "element_type": "parenthetical", "formatted_text": "(whispering)", "status": "approved"},
        {"element_index": 6, "element_type": "dialogue", "formatted_text": "First part of bob speech.", "status": "approved"},
        {"element_index": 7, "element_type": "dialogue", "formatted_text": "Second part of bob speech.", "status": "approved"},
        {"element_index": 8, "element_type": "action", "formatted_text": "Bob steps back.", "status": "approved"},
    ]

    docx_bytes = gen.generate_screenplay_docx(items)
    doc = Document(io.BytesIO(docx_bytes))
    p = doc.paragraphs

    # Action (1) has 12pt space_after
    assert p[1].paragraph_format.space_after.pt == 12

    # Alice character (2) has 0pt space_before (action provides 12pt) and 0pt space_after
    assert p[2].paragraph_format.space_before.pt == 0
    assert p[2].paragraph_format.space_after.pt == 0

    # Alice dialogue (3) has 0pt space_before, and 12pt space_after (ends speech before Bob)
    assert p[3].paragraph_format.space_before.pt == 0
    assert p[3].paragraph_format.space_after.pt == 12

    # Bob character (4) has 0pt space_before and 0pt space_after
    assert p[4].paragraph_format.space_before.pt == 0
    assert p[4].paragraph_format.space_after.pt == 0

    # Bob paren (5) has 0pt space_before and 0pt space_after (compact with character)
    assert p[5].paragraph_format.space_before.pt == 0
    assert p[5].paragraph_format.space_after.pt == 0

    # Bob dialogue 1 (6) has 0pt space_before and 0pt space_after (grouped with dialogue 2)
    assert p[6].paragraph_format.space_before.pt == 0
    assert p[6].paragraph_format.space_after.pt == 0

    # Bob dialogue 2 (7) has 0pt space_before and 12pt space_after (ends speech before Action)
    assert p[7].paragraph_format.space_before.pt == 0
    assert p[7].paragraph_format.space_after.pt == 12


def test_docx_long_action_and_dialogue_allow_page_breaks():
    """Verify that long action and dialogue paragraphs allow natural page breaks."""
    gen = DOCXGenerator()
    long_action = "A " * 200  # 400 characters
    long_dialogue = "Words " * 100  # 600 characters

    items = [
        {"element_index": 0, "element_type": "action", "formatted_text": long_action, "status": "approved"},
        {"element_index": 1, "element_type": "character", "formatted_text": "SPEAKER", "status": "approved"},
        {"element_index": 2, "element_type": "dialogue", "formatted_text": long_dialogue, "status": "approved"},
    ]

    docx_bytes = gen.generate_screenplay_docx(items)
    doc = Document(io.BytesIO(docx_bytes))

    p_action = doc.paragraphs[0]
    assert p_action.paragraph_format.keep_together is not True

    p_diag = doc.paragraphs[2]
    assert p_diag.paragraph_format.keep_together is not True


def test_page_numbers_excluded_from_body_in_docx_and_pdf():
    """Verify that page_number elements are not rendered as inline body text."""
    items = [
        {"element_index": 0, "element_type": "scene_heading", "formatted_text": "INT. ROOM - DAY", "status": "approved"},
        {"element_index": 1, "element_type": "page_number", "formatted_text": "2.", "status": "approved"},
        {"element_index": 2, "element_type": "action", "formatted_text": "Action after page marker.", "status": "approved"},
    ]

    # DOCX
    docx_gen = DOCXGenerator()
    docx_bytes = docx_gen.generate_screenplay_docx(items)
    doc = Document(io.BytesIO(docx_bytes))
    docx_body_texts = [p.text for p in doc.paragraphs]
    assert "2." not in docx_body_texts
    assert len(doc.paragraphs) == 2

    # PDF
    pdf_gen = PDFGenerator()
    pdf_bytes = pdf_gen.generate_screenplay_pdf(items)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 0


# ==============================================================================
# 4. PDF / DOCX Consistency & Multi-page Flow
# ==============================================================================

def test_pdf_and_docx_elements_consistency():
    """Verify PDF and DOCX exports consume identical structured data properly."""
    items = [
        {"element_index": 0, "element_type": "title", "formatted_text": "GENERIC SCRIPT", "status": "approved"},
        {"element_index": 1, "element_type": "author", "formatted_text": "Written by Jane", "status": "approved"},
        {"element_index": 2, "element_type": "scene_heading", "formatted_text": "EXT. PARK - DAY", "status": "approved"},
        {"element_index": 3, "element_type": "action", "formatted_text": "Sunlight filters through leaves.", "status": "approved"},
        {"element_index": 4, "element_type": "character", "formatted_text": "RAINES", "status": "approved"},
        {"element_index": 5, "element_type": "parenthetical", "formatted_text": "(to Dana, low)", "status": "approved"},
        {"element_index": 6, "element_type": "dialogue", "formatted_text": "We're not safe here.", "status": "approved"},
        {"element_index": 7, "element_type": "transition", "formatted_text": "SMASH CUT TO:", "status": "approved"},
        {"element_index": 8, "element_type": "end", "formatted_text": "END", "status": "approved"},
    ]

    docx_bytes = DOCXGenerator().generate_screenplay_docx(items)
    pdf_bytes = PDFGenerator().generate_screenplay_pdf(items)

    assert len(docx_bytes) > 0
    assert len(pdf_bytes) > 0

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pdf_text = "".join(p.extract_text() for p in reader.pages)

    assert "GENERIC SCRIPT" in pdf_text
    assert "EXT. PARK - DAY" in pdf_text
    assert "RAINES" in pdf_text
    assert "(to Dana, low)" in pdf_text
    assert "We're not safe here." in pdf_text
    assert "SMASH CUT TO:" in pdf_text
    assert "END" in pdf_text
