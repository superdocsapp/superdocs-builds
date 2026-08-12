import fitz  # pymupdf


def find_page_for_text(pdf_path: str, search_text: str) -> int | None:
    """Returns the 1-indexed page number where search_text first appears in
    the PDF, or None if not found. This is REAL page detection against the
    actual rendered output — not an estimate, not a count of paragraphs."""
    doc = fitz.open(pdf_path)
    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            if page.search_for(search_text):
                return page_num + 1  # pymupdf is 0-indexed; documents are 1-indexed
        return None
    finally:
        doc.close()


def build_checklist_page_map(pdf_path: str, checklist_items: list[dict]) -> list[dict]:
    """For every checklist item, finds its real page number in the given PDF.
    Items whose anchor text isn't found get page=None, surfaced explicitly
    rather than silently omitted — a missing anchor is itself informative
    (the content may not have been inserted correctly, or wording changed)."""
    results = []
    for entry in checklist_items:
        page = find_page_for_text(pdf_path, entry["anchor_text"])
        results.append({**entry, "page": page})
    return results


if __name__ == "__main__":
    import sys
    from checklist import CHECKLIST_ITEMS

    pdf_path = (
        sys.argv[1] if len(sys.argv) > 1 else "../output/final_review_package.pdf"
    )
    mapped = build_checklist_page_map(pdf_path, CHECKLIST_ITEMS)
    for m in mapped:
        status = f"page {m['page']}" if m["page"] else "NOT FOUND"
        print(f"{m['item']:35s} -> {status}")
