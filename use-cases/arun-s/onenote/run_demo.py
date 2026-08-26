"""Demo runner.

  Offline (no credentials):   python run_demo.py            # re-linearizes sample_page.html and prints it
  Against real OneNote:       GRAPH_TOKEN=... python run_demo.py --page  # lists your pages, exports the first
  With SuperDocs export too:  GRAPH_TOKEN=... SUPERDOCS_API_KEY=... python run_demo.py --page --export
"""
import os
import pathlib
import sys

from relinearize import to_reading_order_html
from graph import OneNote
from superdocs_min import SuperDocs
from export import export_page

HERE = pathlib.Path(__file__).resolve().parent


def offline():
    html = (HERE / "sample_page.html").read_text(encoding="utf-8")
    print("=== reading-order HTML (from sample_page.html) ===\n")
    print(to_reading_order_html(html, title="Sample OneNote Page"))


def live(do_export: bool):
    token = os.getenv("GRAPH_TOKEN")
    if not token:
        sys.exit("Set GRAPH_TOKEN (see README) to talk to OneNote.")
    on = OneNote(token)
    pages = on.list_pages()
    if not pages:
        sys.exit("No OneNote pages found for this account.")
    print("Pages:")
    for p in pages:
        print(" -", p["title"], p["id"])
    page = pages[0]
    print(f"\nRe-linearizing: {page['title']}\n")
    print(to_reading_order_html(on.page_html(page["id"]), title=page["title"])[:1200])
    if do_export:
        if not os.getenv("SUPERDOCS_API_KEY"):
            sys.exit("Set SUPERDOCS_API_KEY to export to SuperDocs.")
        res = export_page(on, SuperDocs(), page["id"], title=page["title"])
        print(f"\nExported to SuperDocs: {res['docx_bytes']} bytes .docx")


if __name__ == "__main__":
    if "--page" in sys.argv:
        live("--export" in sys.argv)
    else:
        offline()
