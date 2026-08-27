"""Build genuine .docx bytes with tracked changes and comments for tests.

python-docx cannot author tracked changes, so we assemble valid OOXML by hand. This produces a
real Word file (a proper zip with the standard parts) that a reviewer's marked-up document looks
exactly like — the parser is therefore tested against reality, not a stub.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# The scenario, with texts tests assert on.
HEADING = "Overview"
_HEAD = "Aurora ships in "
_TAIL = " and targets mid-market teams migrating off spreadsheets."
PARA_ORIGINAL = f"{_HEAD}Q3{_TAIL}"
PARA_PROPOSED = f"{_HEAD}Q4{_TAIL}"
COMMENTED_PARA = "The ingestion service runs on a single Postgres instance behind a queue."
COMMENT_TEXT = "Which Postgres version should we standardise on?"
CHANGE_AUTHOR = "Dana Reviewer"
COMMENT_AUTHOR = "Sam Editor"

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/comments.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
    Target="comments.xml"/>
</Relationships>"""


def _document_xml() -> str:
    date = "2026-08-12T10:00:00Z"
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W}"><w:body>
  <w:p><w:r><w:t>{HEADING}</w:t></w:r></w:p>
  <w:p>
    <w:r><w:t xml:space="preserve">{_HEAD}</w:t></w:r>
    <w:del w:id="1" w:author="{CHANGE_AUTHOR}" w:date="{date}">
      <w:r><w:delText xml:space="preserve">Q3</w:delText></w:r>
    </w:del>
    <w:ins w:id="2" w:author="{CHANGE_AUTHOR}" w:date="{date}">
      <w:r><w:t xml:space="preserve">Q4</w:t></w:r>
    </w:ins>
    <w:r><w:t xml:space="preserve">{_TAIL}</w:t></w:r>
  </w:p>
  <w:p>
    <w:commentRangeStart w:id="0"/>
    <w:r><w:t xml:space="preserve">{COMMENTED_PARA}</w:t></w:r>
    <w:commentRangeEnd w:id="0"/>
    <w:r><w:commentReference w:id="0"/></w:r>
  </w:p>
</w:body></w:document>"""


def _comments_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments xmlns:w="{W}">
  <w:comment w:id="0" w:author="{COMMENT_AUTHOR}" w:date="2026-08-12T11:00:00Z" w:initials="SE">
    <w:p><w:r><w:t>{COMMENT_TEXT}</w:t></w:r></w:p>
  </w:comment>
</w:comments>"""


def build_docx(document_xml: str, comments_xml: str | None = None) -> bytes:
    """Assemble a .docx from the given parts."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        if comments_xml is not None:
            archive.writestr("word/comments.xml", comments_xml)
    return buffer.getvalue()


def reviewed_docx() -> bytes:
    """The standard scenario: one tracked change (Q3→Q4) and one comment."""
    return build_docx(_document_xml(), _comments_xml())


# A second reviewer's copy of the same document. Every reviewer marks up their own copy, so these
# come back separately, each carrying the same review-round id.
SECOND_REVIEWER = "Priya Legal"
OTHER_PARA_INSERT = " It is provisioned as a managed instance."
OTHER_PARA_PROPOSED = COMMENTED_PARA + OTHER_PARA_INSERT
RIVAL_INSERT = " Pricing is not final."
RIVAL_PROPOSED = PARA_ORIGINAL + RIVAL_INSERT


def paragraph_insert_docx(paragraph: str, insertion: str, author: str) -> bytes:
    """One paragraph carrying a tracked insertion by ``author`` — another reviewer's copy."""
    date = "2026-08-14T10:00:00Z"
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>'
        f"<w:p>"
        f'<w:r><w:t xml:space="preserve">{paragraph}</w:t></w:r>'
        f'<w:ins w:id="1" w:author="{author}" w:date="{date}">'
        f'<w:r><w:t xml:space="preserve">{insertion}</w:t></w:r></w:ins>'
        f"</w:p>"
        f"</w:body></w:document>"
    )
    return build_docx(document)


def second_reviewer_docx() -> bytes:
    """A second reviewer editing a *different* paragraph than the first reviewer did."""
    return paragraph_insert_docx(COMMENTED_PARA, OTHER_PARA_INSERT, SECOND_REVIEWER)


def rival_reviewer_docx() -> bytes:
    """A second reviewer editing the *same* paragraph the first reviewer did, differently."""
    return paragraph_insert_docx(PARA_ORIGINAL, RIVAL_INSERT, SECOND_REVIEWER)


def two_tracked_changes_docx() -> bytes:
    """Two tracked changes in one file — so both proposals come from a single chat job."""
    date = "2026-08-14T10:00:00Z"
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>'
        f"<w:p>"
        f'<w:r><w:t xml:space="preserve">{_HEAD}</w:t></w:r>'
        f'<w:del w:id="1" w:author="{CHANGE_AUTHOR}" w:date="{date}">'
        f'<w:r><w:delText xml:space="preserve">Q3</w:delText></w:r></w:del>'
        f'<w:ins w:id="2" w:author="{CHANGE_AUTHOR}" w:date="{date}">'
        f'<w:r><w:t xml:space="preserve">Q4</w:t></w:r></w:ins>'
        f'<w:r><w:t xml:space="preserve">{_TAIL}</w:t></w:r>'
        f"</w:p>"
        f"<w:p>"
        f'<w:r><w:t xml:space="preserve">{COMMENTED_PARA}</w:t></w:r>'
        f'<w:ins w:id="3" w:author="{CHANGE_AUTHOR}" w:date="{date}">'
        f'<w:r><w:t xml:space="preserve">{OTHER_PARA_INSERT}</w:t></w:r></w:ins>'
        f"</w:p>"
        f"</w:body></w:document>"
    )
    return build_docx(document)


# Two identical paragraphs where only the SECOND is edited — for positional matching.
DUP_TEXT = "Repeat me exactly."
DUP_MIDDLE = "A different middle line."
DUP_INSERT = " (edited by the reviewer)"


def duplicate_second_edited_docx() -> bytes:
    """Three paragraphs — two identical, a middle one — with a tracked change on the second copy."""
    date = "2026-08-12T10:00:00Z"
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>'
        f"<w:p><w:r><w:t>{DUP_TEXT}</w:t></w:r></w:p>"
        f"<w:p><w:r><w:t>{DUP_MIDDLE}</w:t></w:r></w:p>"
        f"<w:p>"
        f'<w:r><w:t xml:space="preserve">{DUP_TEXT}</w:t></w:r>'
        f'<w:ins w:id="1" w:author="{CHANGE_AUTHOR}" w:date="{date}">'
        f'<w:r><w:t xml:space="preserve">{DUP_INSERT}</w:t></w:r>'
        f"</w:ins>"
        f"</w:p>"
        f"</w:body></w:document>"
    )
    return build_docx(document)


# A tracked change made INSIDE a hyperlink — the nested case a flat parser drops.
HYPERLINK_ORIGINAL = "See the old page for details."
HYPERLINK_PROPOSED = "See the new page for details."

# A moveFrom/moveTo pair — moved text is original-only, then proposed-only.
MOVE_ORIGINAL = "Alpha. Beta."
MOVE_PROPOSED = "Beta. Alpha."


def hyperlink_tracked_change_docx() -> bytes:
    """A paragraph whose tracked change lives inside a ``w:hyperlink`` wrapper."""
    date = "2026-08-12T10:00:00Z"
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>'
        f"<w:p>"
        f'<w:r><w:t xml:space="preserve">See </w:t></w:r>'
        f"<w:hyperlink>"
        f'<w:del w:id="1" w:author="{CHANGE_AUTHOR}" w:date="{date}">'
        f'<w:r><w:delText xml:space="preserve">the old page</w:delText></w:r></w:del>'
        f'<w:ins w:id="2" w:author="{CHANGE_AUTHOR}" w:date="{date}">'
        f'<w:r><w:t xml:space="preserve">the new page</w:t></w:r></w:ins>'
        f"</w:hyperlink>"
        f'<w:r><w:t xml:space="preserve"> for details.</w:t></w:r>'
        f"</w:p>"
        f"</w:body></w:document>"
    )
    return build_docx(document)


def moved_text_docx() -> bytes:
    """A paragraph with a ``w:moveFrom`` / ``w:moveTo`` revision pair."""
    date = "2026-08-12T10:00:00Z"
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>'
        f"<w:p>"
        f'<w:moveFrom w:id="1" w:author="{CHANGE_AUTHOR}" w:date="{date}">'
        f'<w:r><w:t xml:space="preserve">Alpha. </w:t></w:r></w:moveFrom>'
        f'<w:r><w:t xml:space="preserve">Beta.</w:t></w:r>'
        f'<w:moveTo w:id="2" w:author="{CHANGE_AUTHOR}" w:date="{date}">'
        f'<w:r><w:t xml:space="preserve"> Alpha.</w:t></w:r></w:moveTo>'
        f"</w:p>"
        f"</w:body></w:document>"
    )
    return build_docx(document)


# A packet of two pages, one paragraph each, both edited — for multi-document fan-out.
PACKET_P1_ORIGINAL = "The alpha service handles ingestion."
PACKET_P1_PROPOSED = "The alpha service handles ingestion and validation."
PACKET_P2_ORIGINAL = "The beta service handles delivery."
PACKET_P2_PROPOSED = "The beta service handles delivery and receipts."


def packet_review_docx() -> bytes:
    """One reviewer paragraph from each page of a two-page packet, each with a tracked insertion."""
    date = "2026-08-12T10:00:00Z"
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>'
        f"<w:p>"
        f'<w:r><w:t xml:space="preserve">The alpha service handles ingestion</w:t></w:r>'
        f'<w:ins w:id="1" w:author="{CHANGE_AUTHOR}" w:date="{date}">'
        f'<w:r><w:t xml:space="preserve"> and validation</w:t></w:r></w:ins>'
        f'<w:r><w:t xml:space="preserve">.</w:t></w:r>'
        f"</w:p>"
        f"<w:p>"
        f'<w:r><w:t xml:space="preserve">The beta service handles delivery</w:t></w:r>'
        f'<w:ins w:id="2" w:author="{COMMENT_AUTHOR}" w:date="{date}">'
        f'<w:r><w:t xml:space="preserve"> and receipts</w:t></w:r></w:ins>'
        f'<w:r><w:t xml:space="preserve">.</w:t></w:r>'
        f"</w:p>"
        f"</w:body></w:document>"
    )
    return build_docx(document)


# A comment that is an edit REQUEST (not a question) — SuperDocs' AI should author an edit.
INTENT_PARA = "The ingestion service runs on a single Postgres instance behind a queue."
INTENT_COMMENT = "Make this sentence concise and professional."


# A reviewer QUESTION only the owner can answer — must never become an AI-authored edit.
QUESTION_PARA = "The service targets ninety-nine point nine percent availability."
QUESTION_COMMENT = "Which region should we deploy this in first?"


def question_comment_docx() -> bytes:
    """One paragraph with a question comment (no edit intent)."""
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>'
        f"<w:p>"
        f'<w:commentRangeStart w:id="0"/>'
        f'<w:r><w:t xml:space="preserve">{QUESTION_PARA}</w:t></w:r>'
        f'<w:commentRangeEnd w:id="0"/>'
        f'<w:r><w:commentReference w:id="0"/></w:r>'
        f"</w:p>"
        f"</w:body></w:document>"
    )
    comments = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:comments xmlns:w="{W}">'
        f'<w:comment w:id="0" w:author="{COMMENT_AUTHOR}" w:date="2026-08-12T11:00:00Z" '
        f'w:initials="SE"><w:p><w:r><w:t>{QUESTION_COMMENT}</w:t></w:r></w:p></w:comment>'
        f"</w:comments>"
    )
    return build_docx(document, comments)


def comment_intent_docx() -> bytes:
    """One paragraph carrying a directive comment (an edit request), no tracked change."""
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>'
        f"<w:p>"
        f'<w:commentRangeStart w:id="0"/>'
        f'<w:r><w:t xml:space="preserve">{INTENT_PARA}</w:t></w:r>'
        f'<w:commentRangeEnd w:id="0"/>'
        f'<w:r><w:commentReference w:id="0"/></w:r>'
        f"</w:p>"
        f"</w:body></w:document>"
    )
    comments = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:comments xmlns:w="{W}">'
        f'<w:comment w:id="0" w:author="{COMMENT_AUTHOR}" w:date="2026-08-12T11:00:00Z" '
        f'w:initials="SE"><w:p><w:r><w:t>{INTENT_COMMENT}</w:t></w:r></w:p></w:comment>'
        f"</w:comments>"
    )
    return build_docx(document, comments)


# A tracked change that smuggles in a link and script-like content — for the security rails.
LINK_ORIGINAL = "See the internal wiki for details."
LINK_PROPOSED = "See https://evil.example.com and run <script>steal()</script> for details."


def link_and_script_docx() -> bytes:
    """A tracked change whose proposed text contains a URL and a script-looking string."""
    date = "2026-08-13T10:00:00Z"
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>'
        f"<w:p>"
        f'<w:r><w:t xml:space="preserve">See </w:t></w:r>'
        f'<w:del w:id="1" w:author="{CHANGE_AUTHOR}" w:date="{date}">'
        f"<w:r><w:delText>the internal wiki</w:delText></w:r></w:del>"
        f'<w:ins w:id="2" w:author="{CHANGE_AUTHOR}" w:date="{date}">'
        f'<w:r><w:t xml:space="preserve">https://evil.example.com and run '
        f"&lt;script&gt;steal()&lt;/script&gt;</w:t></w:r></w:ins>"
        f'<w:r><w:t xml:space="preserve"> for details.</w:t></w:r>'
        f"</w:p>"
        f"</w:body></w:document>"
    )
    return build_docx(document)


def unchanged_docx(text: str) -> bytes:
    """A .docx with a single, unmodified paragraph — no tracked changes, no comments."""
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>'
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        f"</w:body></w:document>"
    )
    return build_docx(document)


def zip_with_too_many_members() -> bytes:
    """A zip that trips the member-count guard."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for i in range(2100):
            archive.writestr(f"part{i}.xml", b"x")
    return buffer.getvalue()
