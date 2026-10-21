"""
Post-process a SuperDocs-exported DOCX to embed product images.

SuperDocs receives only text instructions with document_id references and
cannot access our local filesystem. After downloading the DOCX, this module
finds the "Product Images" heading and inserts the actual image bytes.
"""

from io import BytesIO
from pathlib import Path
from typing import List, Dict, Any

from docx import Document
from docx.shared import Inches

from backend.logging_config import get_logger

logger = get_logger(__name__)

PRODUCT_IMAGES_HEADING = "Product Images"


def embed_images_in_docx(
    docx_path: str,
    images: List[Dict[str, Any]],
) -> bool:
    """
    Embed product images into an existing DOCX file under the
    "Product Images" heading.

    Args:
        docx_path: Absolute path to the DOCX file (modified in-place).
        images: List of {"bytes": bytes, "filename": str} dicts.

    Returns:
        True if at least one image was embedded, False otherwise.
    """
    if not images:
        logger.info("no_images_to_embed", docx_path=docx_path)
        return False

    path = Path(docx_path)
    if not path.exists():
        logger.warning("docx_not_found_for_image_embed", docx_path=docx_path)
        return False

    doc = Document(docx_path)
    paragraphs = doc.paragraphs

    # Find the "Product Images" heading paragraph index
    heading_idx = None
    for i, para in enumerate(paragraphs):
        if para.style.name.startswith("Heading") and para.text.strip() == PRODUCT_IMAGES_HEADING:
            heading_idx = i
            break

    if heading_idx is None:
        logger.warning(
            "product_images_heading_not_found",
            docx_path=docx_path,
        )
        return False

    # Find the insertion point: right after the heading, skipping any blank
    # paragraphs that SuperDocs may have left as placeholders.
    insert_after_idx = heading_idx
    for j in range(heading_idx + 1, len(paragraphs)):
        if paragraphs[j].text.strip() == "":
            insert_after_idx = j
        else:
            break

    embedded = 0
    # We insert images in reverse order so each insert-after the same anchor
    # ends up in correct order.
    for img in reversed(images):
        img_bytes = img.get("bytes")
        filename = img.get("filename", "image")

        if not img_bytes:
            logger.warning("image_bytes_missing", filename=filename)
            continue

        try:
            _insert_image_after(doc, insert_after_idx, img_bytes, filename)
            embedded += 1
            logger.info("image_embedded", filename=filename)
        except Exception as exc:
            logger.warning(
                "image_embed_failed",
                filename=filename,
                error=str(exc),
            )

    if embedded == 0:
        return False

    doc.save(docx_path)
    logger.info(
        "docx_images_embedded",
        docx_path=docx_path,
        embedded=embedded,
    )
    return True


def _insert_image_after(
    doc: Document,
    para_idx: int,
    img_bytes: bytes,
    filename: str,
) -> None:
    """
    Insert a caption paragraph and an image paragraph immediately after
    the paragraph at para_idx in doc.

    python-docx has no public insert API, so we manipulate the underlying
    XML directly (the standard approach for this operation).
    """
    from docx.oxml.ns import qn
    from lxml import etree
    import copy

    body = doc.element.body

    # Reference paragraph (the one we insert after)
    ref_para = doc.paragraphs[para_idx]._element

    # --- Caption paragraph ---
    cap_para = doc.add_paragraph(filename)
    cap_para.runs[0].italic = True
    cap_element = cap_para._element
    # Detach from end of body, re-insert after ref_para
    body.remove(cap_element)
    ref_para.addnext(cap_element)

    # --- Image paragraph ---
    img_para = doc.add_paragraph()
    run = img_para.add_run()
    run.add_picture(BytesIO(img_bytes), width=Inches(4.0))
    img_element = img_para._element
    body.remove(img_element)
    cap_element.addnext(img_element)
