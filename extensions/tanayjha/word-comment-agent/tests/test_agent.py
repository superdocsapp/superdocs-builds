import os
import tempfile
import pytest
from docx import Document
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.opc.part import XmlPart
from docx.opc.packuri import PackURI

from src.mcp_server import (
    propose_comment_edits,
    review_comment_changes,
    export_word_document,
    REVIEW_CONTEXTS,
    LATEST_REVIEW_PER_COMMENT
)
from src.docx_writer import apply_edits_and_resolve_comments

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_COMMENTS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"

def create_sample_docx_with_comment(
    path: str,
    comment_id: str = "1",
    prefix_text: str = "Before anchor. ",
    anchor_text: str = "This is anchor text.",
    suffix_text: str = " After anchor.",
    comment_instruction: str = "Please revise this text.",
    anchor_is_bold: bool = False
):
    """
    Creates a valid test .docx document with comment range start/end and comments.xml.
    Includes a leading run before commentRangeStart to test structural mid-run behavior.
    """
    doc = Document()
    p = doc.add_paragraph()

    # Preceding run
    if prefix_text:
        r_pre = p.add_run(prefix_text)

    # Comment range start marker
    c_start = OxmlElement('w:commentRangeStart')
    c_start.set(qn('w:id'), comment_id)
    p._p.append(c_start)

    # Anchor run
    r_anchor = p.add_run(anchor_text)
    if anchor_is_bold:
        r_anchor.bold = True

    # Comment range end marker
    c_end = OxmlElement('w:commentRangeEnd')
    c_end.set(qn('w:id'), comment_id)
    p._p.append(c_end)

    # Comment reference marker
    c_ref = OxmlElement('w:commentReference')
    c_ref.set(qn('w:id'), comment_id)
    p._p.append(c_ref)

    # Following run
    if suffix_text:
        r_post = p.add_run(suffix_text)

    # Create comments.xml part
    comments_part_xml = parse_xml(
        f'<w:comments xmlns:w="{W_NS}">'
        f'  <w:comment w:id="{comment_id}" w:author="Tester">'
        f'    <w:p><w:r><w:t>{comment_instruction}</w:t></w:r></w:p>'
        f'  </w:comment>'
        f'</w:comments>'
    )
    
    # Add comments part to document using XmlPart
    comments_part = XmlPart(
        PackURI('/word/comments.xml'),
        'application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml',
        comments_part_xml,
        doc.part.package
    )
    doc.part.relate_to(comments_part, REL_COMMENTS)
    
    doc.save(path)
    return path

def test_post_export_verification():
    """Test Fix 4: Verification oracle verifies text match and returns verification_status."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_file = os.path.join(tmpdir, "test_verification.docx")
        output_file = os.path.join(tmpdir, "output_verification.docx")
        create_sample_docx_with_comment(input_file, comment_id="1", anchor_text="Original text.")

        # Test valid matching export
        res = apply_edits_and_resolve_comments(
            input_path=input_file,
            output_path=output_file,
            approved_edits=[{"comment_id": "1", "replacement_text": "Updated verified text."}]
        )

        assert res["verified"] is True
        assert res["verification_status"] == "success"
        assert len(res["verification_mismatches"]) == 0

def test_p4_stale_text_regression():
    """Test Fix 1 / P4 Regression: Propose -> Re-propose -> Approve -> Export asserts second proposal is exported."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_file = os.path.join(tmpdir, "test_p4.docx")
        output_file = os.path.join(tmpdir, "output_p4.docx")
        create_sample_docx_with_comment(input_file, comment_id="1", anchor_text="Target anchor text")

        # First proposal run (mock API)
        os.environ["SUPERDOCS_API_KEY"] = "mock"
        res1 = propose_comment_edits(input_file)
        rev_id1 = res1["review_id"]
        assert rev_id1 is not None

        # Second proposal run (simulating re-propose with updated edit)
        res2 = propose_comment_edits(input_file)
        rev_id2 = res2["review_id"]
        assert rev_id2 != rev_id1

        # Approve second review ID with explicit text override
        review_comment_changes(rev_id2, [{"comment_id": "1", "approved": True, "override_text": "Second proposed text"}])

        # Export second review ID
        export_res = export_word_document(rev_id2, output_file)
        assert export_res["verified"] is True

        # Assert output document contains the SECOND proposal text
        doc_out = Document(output_file)
        full_text = "".join([p.text for p in doc_out.paragraphs])
        assert "Second proposed text" in full_text
        assert "Mock revised text" not in full_text

def test_stale_review_id_rejection():
    """Test Fix 1: Attempting to export an old/superseded review_id raises ValueError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_file = os.path.join(tmpdir, "test_stale.docx")
        output_file = os.path.join(tmpdir, "output_stale.docx")
        create_sample_docx_with_comment(input_file, comment_id="1")

        res1 = propose_comment_edits(input_file)
        rev_id1 = res1["review_id"]

        # Re-propose to supersede rev_id1
        res2 = propose_comment_edits(input_file)
        rev_id2 = res2["review_id"]

        review_comment_changes(rev_id1, [{"comment_id": "1", "approved": True}])

        # Exporting rev_id1 must fail due to staleness check
        with pytest.raises(ValueError, match="Stale review session ID"):
            export_word_document(rev_id1, output_file)

def test_override_text_in_review():
    """Test Fix 1: Human override_text in review_comment_changes updates proposal text prior to export."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_file = os.path.join(tmpdir, "test_override.docx")
        output_file = os.path.join(tmpdir, "output_override.docx")
        create_sample_docx_with_comment(input_file, comment_id="1", anchor_text="Original anchor text")

        res = propose_comment_edits(input_file)
        rev_id = res["review_id"]

        human_override = "Human confirmed exact text override."
        review_comment_changes(rev_id, [{"comment_id": "1", "approved": True, "override_text": human_override}])

        export_res = export_word_document(rev_id, output_file)
        assert export_res["verified"] is True

        doc_out = Document(output_file)
        full_text = "".join([p.text for p in doc_out.paragraphs])
        assert human_override in full_text

def test_no_text_duplication():
    """Test Fix 2: Mid-run anchor replacement does not duplicate preceding or following text."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_file = os.path.join(tmpdir, "test_dup.docx")
        output_file = os.path.join(tmpdir, "output_dup.docx")
        
        prefix = "Paragraph prefix context. "
        anchor = "anchored section"
        suffix = " Paragraph suffix context."
        create_sample_docx_with_comment(input_file, comment_id="1", prefix_text=prefix, anchor_text=anchor, suffix_text=suffix)

        # Model returns replacement that accidentally includes prefix/suffix context
        model_replacement_with_context = f"{prefix}revised section{suffix}"

        res = apply_edits_and_resolve_comments(
            input_path=input_file,
            output_path=output_file,
            approved_edits=[{"comment_id": "1", "replacement_text": model_replacement_with_context}]
        )

        doc_out = Document(output_file)
        full_text = doc_out.paragraphs[0].text
        
        # Verify no duplication occurred
        expected_full_paragraph = "Paragraph prefix context. revised section Paragraph suffix context."
        assert full_text == expected_full_paragraph
        assert full_text.count("Paragraph prefix context.") == 1

def test_formatting_preservation():
    """Test Fix 3a: Unwanted bolding is not introduced on unbolded anchor runs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_file = os.path.join(tmpdir, "test_fmt.docx")
        output_file = os.path.join(tmpdir, "output_fmt.docx")
        
        # Create unbolded anchor
        create_sample_docx_with_comment(input_file, comment_id="1", anchor_text="Unbolded anchor", anchor_is_bold=False)

        res = apply_edits_and_resolve_comments(
            input_path=input_file,
            output_path=output_file,
            approved_edits=[{"comment_id": "1", "replacement_text": "Clean replacement text"}]
        )

        doc_out = Document(output_file)
        target_run = doc_out.paragraphs[0].runs[1]  # Anchor run position
        # Verify run bold property is False or None
        assert target_run.bold in (False, None)
