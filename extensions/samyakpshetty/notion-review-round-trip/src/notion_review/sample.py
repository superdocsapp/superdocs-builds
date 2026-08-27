"""Sample data for the keyless demo: a Notion page and a marked-up Word review of it.

This lets ``make demo`` run the whole round-trip with no API keys — a real Notion-shaped page
and a real tracked-changes .docx, driven through the same code path the live product uses.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

from notion_review.notion import FakeNotionClient

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# Paragraphs in the demo page (mirrors FakeNotionClient.build_sample) that the review touches.
_TAIL = " and targets mid-market teams migrating off spreadsheets."
_INGESTION = "The ingestion service runs on a single Postgres instance behind a queue."


def demo_page() -> tuple[FakeNotionClient, str]:
    """The Notion page a team sends out for review."""
    return FakeNotionClient.build_sample()


def demo_review_docx() -> bytes:
    """A reviewer's marked-up Word file: one tracked change (Q3→Q4) and one comment."""
    date = "2026-08-12T10:00:00Z"
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{_W}"><w:body>
  <w:p>
    <w:r><w:t xml:space="preserve">Aurora ships in </w:t></w:r>
    <w:del w:id="1" w:author="Dana Reviewer" w:date="{date}">
      <w:r><w:delText xml:space="preserve">Q3</w:delText></w:r>
    </w:del>
    <w:ins w:id="2" w:author="Dana Reviewer" w:date="{date}">
      <w:r><w:t xml:space="preserve">Q4</w:t></w:r>
    </w:ins>
    <w:r><w:t xml:space="preserve">{_TAIL}</w:t></w:r>
  </w:p>
  <w:p>
    <w:commentRangeStart w:id="0"/>
    <w:r><w:t xml:space="preserve">{_INGESTION}</w:t></w:r>
    <w:commentRangeEnd w:id="0"/>
    <w:r><w:commentReference w:id="0"/></w:r>
  </w:p>
</w:body></w:document>"""
    comments = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="{_W}">
  <w:comment w:id="0" w:author="Sam Editor" w:date="{date}" w:initials="SE">
    <w:p><w:r><w:t>Which Postgres version should we standardise on?</w:t></w:r></w:p>
  </w:comment>
</w:comments>"""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/comments.xml", comments)
    return buffer.getvalue()
