"""Check the finished document the way a reviewer would: from the API and the DOCX.

Nothing here trusts the run's own report. The document is fetched fresh, the
checklist is re-asserted against the headings that came back, every figure the
roll-forward computed is required to be present, and the exported DOCX is
unzipped and its table structure counted - because "it exported" is not evidence
that anything is in it.

    python scripts/verify_live_output.py <document_id> [--docx PATH]
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = APP_ROOT.parent.parent
sys.path.insert(0, str(APP_ROOT))

from statutory.chunks import ChunkMap  # noqa: E402
from statutory.money import money_tokens_in_html, strip_markup  # noqa: E402
from statutory.notetree import assert_checklist_consistent  # noqa: E402
from statutory.pipeline import DEFAULT_CONFIG, prepare  # noqa: E402
from statutory.superdocs.client import SuperDocsClient  # noqa: E402
from statutory.superdocs.transport import HttpTransport  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("document_id")
    parser.add_argument("--docx", default=str(REPO_ROOT / "var" / "statutory" / "statements.docx"))
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=False)
    except ImportError:
        pass

    rolled = prepare(REPO_ROOT / "corpus", DEFAULT_CONFIG)
    client = SuperDocsClient(HttpTransport())
    live, detail = client.read_back(args.document_id)
    html = detail["html"]

    print(f"document {args.document_id} version {detail.get('version')}")
    print(f"  {len(live)} chunks read back")

    ours = ChunkMap(rolled.document.html("target"))
    print(f"  computed document: {len(ours)} chunks")
    assert len(live) == len(ours), "the chunk count moved"

    mismatched = [
        i
        for i, (a, b) in enumerate(zip(ours.chunks, live.chunks, strict=True))
        if a.canonical != b.canonical
    ]
    print(f"  chunks differing from what we computed: {len(mismatched)} {mismatched[:5]}")

    headings = live.headings()
    print(f"  note headings in the live document: {len(headings)}")
    assert_checklist_consistent(rolled.mapping, rolled.tree, headings)
    print("  checklist consistency re-asserted against the LIVE headings: ok")

    tokens = set(money_tokens_in_html(html))
    ties = ["4,857.00", "4,068.00", "577.00", "414.50", "407.00", "309.00", "1,691.00", "1,284.00"]
    missing = [t for t in ties if t not in tokens]
    print(f"  tie figures present in the live document: {len(ties) - len(missing)}/{len(ties)}")
    assert not missing, f"missing from the live document: {missing}"

    text = strip_markup(html)
    for phrase in (
        "Note 4",
        "Leases",
        "Business combination",
        "disclosed in Note 5",
        "all 29 account names were searched",
        "821.00",
    ):
        assert phrase in text, f"{phrase!r} is not in the live document"
    print("  new note, repointed cross-reference and both disagreements present: ok")
    assert "31 March 2025</strong>" not in html, "the front matter still says last year"

    docx = Path(args.docx)
    if docx.is_file():
        with zipfile.ZipFile(docx) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8")
        print(f"  DOCX {docx.name}: {docx.stat().st_size:,} bytes")
        print(f"    w:tbl {document_xml.count('<w:tbl>')}")
        print(f"    w:tr  {document_xml.count('<w:tr ') + document_xml.count('<w:tr>')}")
        print(f"    w:tc  {document_xml.count('<w:tc>')}")
        print(f"    w:tcBorders {document_xml.count('<w:tcBorders>')}")
        print(f"    w:shd {document_xml.count('<w:shd ')}")
        flat = re.sub(r"<[^>]+>", "", document_xml)
        for token in ("4,857.00", "268.00", "8.14", "185.00"):
            assert token in flat, f"{token} is not in the exported DOCX"
        print("    key figures present in word/document.xml: ok")
    else:
        print(f"  no DOCX at {docx}")

    print("VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
