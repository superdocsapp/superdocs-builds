import os
from typing import List, Dict, Any, Optional
from docx import Document
from docx.oxml import parse_xml

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_COMMENTS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"

NO_CHANGE_PHRASES = [
    "no change needed",
    "no changes needed",
    "lgtm",
    "no edit needed",
    "no edit required",
    "looks good",
    "keep as is",
    "no action needed"
]

def is_no_change_comment(comment_text: str) -> bool:
    """
    Returns True if the comment text indicates no changes are required.
    """
    clean_text = comment_text.strip().lower()
    for phrase in NO_CHANGE_PHRASES:
        if phrase in clean_text:
            return True
    return False

def get_comments_part_xml(doc: Document) -> Optional[Any]:
    """
    Retrieves the root <w:comments> XML element if it exists in the document.
    """
    for rel in doc.part.rels.values():
        if rel.reltype == REL_COMMENTS:
            return rel.target_part.element
    return None

def extract_anchor_text_for_comment(doc: Document, comment_id: str) -> str:
    """
    Extracts the text between <w:commentRangeStart w:id="..."> and <w:commentRangeEnd w:id="...">
    in the main document body.
    """
    body_elm = doc.part.element.body
    start_tag = f"{{{W_NS}}}commentRangeStart"
    end_tag = f"{{{W_NS}}}commentRangeEnd"
    text_tag = f"{{{W_NS}}}t"
    
    in_range = False
    anchor_texts = []

    # Traverse all elements in document body sequentially
    for elem in body_elm.iter():
        elem_comment_id = elem.get(f"{{{W_NS}}}id") or elem.get("w:id")
        
        if elem.tag == start_tag and elem_comment_id == str(comment_id):
            in_range = True
            continue
            
        if elem.tag == end_tag and elem_comment_id == str(comment_id):
            in_range = False
            break
            
        if in_range and elem.tag == text_tag and elem.text:
            anchor_texts.append(elem.text)

    return "".join(anchor_texts).strip()

def extract_docx_comments(file_path: str) -> Dict[str, Any]:
    """
    Parses a .docx file and extracts all unresolved comments and their anchored target text.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    doc = Document(file_path)
    comments_elm = get_comments_part_xml(doc)
    
    if comments_elm is None:
        return {
            "document_path": file_path,
            "unresolved_count": 0,
            "comments": []
        }

    comment_nodes = comments_elm.findall(f"{{{W_NS}}}comment")
    unresolved_comments = []

    for c_node in comment_nodes:
        comment_id = c_node.get(f"{{{W_NS}}}id") or c_node.get("w:id")
        
        # Check if resolved (w:done="1" or w:resolved="1")
        is_done = c_node.get(f"{{{W_NS}}}done") == "1" or c_node.get("w:done") == "1"
        is_resolved = c_node.get(f"{{{W_NS}}}resolved") == "1" or c_node.get("w:resolved") == "1"
        if is_done or is_resolved:
            continue

        author = c_node.get(f"{{{W_NS}}}author") or c_node.get("w:author") or "Unknown"
        
        # Extract comment text from <w:t> elements inside <w:comment>
        text_nodes = c_node.findall(f".//{{{W_NS}}}t")
        comment_text = "".join([t.text for t in text_nodes if t.text]).strip()

        # Extract anchor text from main document
        anchor_text = extract_anchor_text_for_comment(doc, comment_id)
        
        no_change = is_no_change_comment(comment_text)

        unresolved_comments.append({
            "comment_id": str(comment_id),
            "author": author,
            "instruction": comment_text,
            "anchor_text": anchor_text,
            "no_change_needed": no_change
        })

    return {
        "document_path": file_path,
        "unresolved_count": len(unresolved_comments),
        "comments": unresolved_comments
    }
