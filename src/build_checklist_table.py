def build_checklist_html(page_mapped_items: list[dict]) -> str:
    """Builds an HTML table from checklist items with their detected page
    numbers. Items with page=None (anchor not found) are shown explicitly
    as 'Not found' rather than omitted — a missing item is information the
    reviewer needs, not something to silently drop."""
    html = [
        "<h3>Reporting Checklist</h3>",
        '<table style="border-collapse: collapse; width: 100%; font-size: 0.9em;">',
        "<thead><tr>",
        '<th style="border: 1px solid #333; padding: 6px; background: #f0f0f0; text-align: left;">Item</th>',
        '<th style="border: 1px solid #333; padding: 6px; background: #f0f0f0; text-align: left;">Description</th>',
        '<th style="border: 1px solid #333; padding: 6px; background: #f0f0f0; text-align: center;">Page</th>',
        "</tr></thead><tbody>",
    ]

    for entry in page_mapped_items:
        page_display = str(entry["page"]) if entry["page"] else "Not found"
        row_style = "" if entry["page"] else ' style="background: #fff3cd;"'
        html.append(f"<tr{row_style}>")
        html.append(
            f'<td style="border: 1px solid #333; padding: 6px;">{entry["item"]}</td>'
        )
        html.append(
            f'<td style="border: 1px solid #333; padding: 6px;">{entry["description"]}</td>'
        )
        html.append(
            f'<td style="border: 1px solid #333; padding: 6px; text-align: center;">{page_display}</td>'
        )
        html.append("</tr>")

    html.append("</tbody></table>")
    return "".join(html)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from checklist import CHECKLIST_ITEMS
    from page_finder import build_checklist_page_map

    pdf_path = (
        sys.argv[1] if len(sys.argv) > 1 else "../output/final_review_package.pdf"
    )
    mapped = build_checklist_page_map(pdf_path, CHECKLIST_ITEMS)
    print(build_checklist_html(mapped)[:500], "...")
