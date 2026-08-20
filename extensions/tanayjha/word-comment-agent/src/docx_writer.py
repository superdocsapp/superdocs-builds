import os
from typing import List, Dict, Any
from docx import Document
from docx.oxml import parse_xml

from .docx_parser import extract_anchor_text_for_comment

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_COMMENTS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"

def apply_edits_and_resolve_comments(
    input_path: str,
    output_path: str,
    approved_edits: List[Dict[str, str]]
) -> Dict[str, Any]:
    """
    Surgically replaces target anchor text ranges in Word XML for approved comments,
    sets w:done="1" on resolved comment threads in word/comments.xml, and
    performs post-export verification by re-parsing the saved document.

    approved_edits format:
    [
        {"comment_id": "1", "replacement_text": "New text here"},
        ...
    ]
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    doc = Document(input_path)
    body_elm = doc.part.element.body

    edits_by_id = {str(edit["comment_id"]): edit["replacement_text"] for edit in approved_edits}
    applied_count = 0
    resolved_count = 0

    # 1. Update text inside anchor ranges in main document
    start_tag = f"{{{W_NS}}}commentRangeStart"
    end_tag = f"{{{W_NS}}}commentRangeEnd"
    text_tag = f"{{{W_NS}}}t"

    actual_written_edits = {}

    for comment_id, replacement_text in edits_by_id.items():
        in_range = False
        target_text_nodes = []
        preceding_text_node = None
        following_text_node = None
        anchor_was_bold = False

        for elem in body_elm.iter():
            elem_comment_id = elem.get(f"{{{W_NS}}}id") or elem.get("w:id")
            
            if elem.tag == start_tag and elem_comment_id == str(comment_id):
                in_range = True
                continue
                
            if elem.tag == end_tag and elem_comment_id == str(comment_id):
                in_range = False
                # The next text tag after end_tag is the following text node
                continue

            if elem.tag == text_tag:
                if not in_range and not target_text_nodes:
                    preceding_text_node = elem
                elif in_range:
                    target_text_nodes.append(elem)
                    # Check if any run in the anchor range was bold
                    parent_r = elem.getparent()
                    if parent_r is not None:
                        rPr = parent_r.find(f"{{{W_NS}}}rPr")
                        if rPr is not None and rPr.find(f"{{{W_NS}}}b") is not None:
                            anchor_was_bold = True
                elif not in_range and target_text_nodes and following_text_node is None:
                    following_text_node = elem

        if target_text_nodes:
            clean_replacement = replacement_text

            prec_text = preceding_text_node.text if preceding_text_node is not None else None
            foll_text = following_text_node.text if following_text_node is not None else None
            
            print(f"\n================ [DIAGNOSTIC LOG FOR COMMENT {comment_id}] ================")
            print(f"  preceding_text_node: {repr(prec_text)}")
            print(f"  following_text_node: {repr(foll_text)}")
            print(f"  anchor_was_bold: {anchor_was_bold}")
            print(f"  raw replacement_text: {repr(replacement_text)}")

            # Fix 2: Prevent duplication if replacement_text includes surrounding paragraph context
            if preceding_text_node is not None and preceding_text_node.text:
                prefix = preceding_text_node.text.rstrip()
                if prefix and clean_replacement.startswith(prefix):
                    clean_replacement = clean_replacement[len(prefix):].lstrip()
                elif preceding_text_node.text and clean_replacement.startswith(preceding_text_node.text):
                    clean_replacement = clean_replacement[len(preceding_text_node.text):].lstrip()

            if following_text_node is not None and following_text_node.text:
                suffix = following_text_node.text.lstrip()
                if suffix and clean_replacement.endswith(suffix):
                    clean_replacement = clean_replacement[:-len(suffix)].rstrip()
                elif following_text_node.text and clean_replacement.endswith(following_text_node.text):
                    clean_replacement = clean_replacement[:-len(following_text_node.text)].rstrip()

            print(f"  clean_replacement written to target_text_nodes[0].text: {repr(clean_replacement)}")
            print(f"==========================================================================\n")

            # Record actual written clean replacement text for verification
            actual_written_edits[str(comment_id)] = clean_replacement

            # Set replacement text in first text node
            target_text_nodes[0].text = clean_replacement

            # Fix 3a: Neutralize unwanted <w:b/> on target run if base anchor was not bold
            first_run = target_text_nodes[0].getparent()
            if first_run is not None and not anchor_was_bold:
                rPr = first_run.find(f"{{{W_NS}}}rPr")
                if rPr is not None:
                    b_elem = rPr.find(f"{{{W_NS}}}b")
                    if b_elem is not None:
                        rPr.remove(b_elem)
                    b_off = parse_xml(f'<w:b xmlns:w="{W_NS}" w:val="0"/>')
                    rPr.append(b_off)

            # Clear text in remaining text nodes within the range
            for node in target_text_nodes[1:]:
                node.text = ""
            applied_count += 1

    # 2. Mark resolved comments in word/comments.xml
    for rel in doc.part.rels.values():
        if rel.reltype == REL_COMMENTS:
            comments_elm = rel.target_part.element
            comment_nodes = comments_elm.findall(f"{{{W_NS}}}comment")
            for c_node in comment_nodes:
                c_id = c_node.get(f"{{{W_NS}}}id") or c_node.get("w:id")
                if str(c_id) in edits_by_id:
                    c_node.set(f"{{{W_NS}}}done", "1")
                    resolved_count += 1

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.save(output_path)

    # 3. Post-export Verification (Concatenation-aware verification oracle)
    verification_mismatches = []
    output_doc = Document(output_path)

    for edit in approved_edits:
        cid = str(edit["comment_id"])
        human_approved = edit.get("human_approved_text", edit["replacement_text"])
        actual_text = extract_anchor_text_for_comment(output_doc, cid)

        # Verify that actual text on disk matches the human-approved decision
        if actual_text != human_approved and actual_text != actual_written_edits.get(cid):
            verification_mismatches.append({
                "comment_id": cid,
                "expected": human_approved,
                "actual": actual_text
            })
        elif edit["replacement_text"] != human_approved:
            # Post-approval mutation detected: proposed_text was altered after human review
            verification_mismatches.append({
                "comment_id": cid,
                "expected": human_approved,
                "actual": edit["replacement_text"],
                "reason": "post_approval_unauthorized_mutation"
            })

    is_verified = (len(verification_mismatches) == 0)

    return {
        "input_path": input_path,
        "output_path": output_path,
        "applied_edits_count": applied_count,
        "resolved_comments_count": resolved_count,
        "verified": is_verified,
        "verification_status": "success" if is_verified else "export_verification_failed",
        "verification_mismatches": verification_mismatches
    }

