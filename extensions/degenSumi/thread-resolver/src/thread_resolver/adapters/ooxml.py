"""Namespaces and part names of the WordprocessingML comment format.

Comment threads are spread across three parts of the .docx zip:

    word/document.xml           body text and the ranges comments are anchored to
    word/comments.xml           comment author, date and text
    word/commentsExtended.xml   reply parentage and resolved state

Reply parentage and resolved state exist only in the third part, and it is
optional. A document written by a tool that omits it has comments but no
recoverable thread structure.

Two identifiers connect the parts:

    w:id        integer, links a comment to its anchor range in the body
    w14:paraId  8-digit hex on a paragraph, used by commentsExtended to name a
                comment and to point at the comment it replies to
"""

from __future__ import annotations

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
XML = "http://www.w3.org/XML/1998/namespace"

NSMAP = {"w": W, "w14": W14, "w15": W15, "r": R}

DOCUMENT_PART = "word/document.xml"
COMMENTS_PART = "word/comments.xml"
COMMENTS_EXTENDED_PART = "word/commentsExtended.xml"


def qn(tag: str) -> str:
    """Expand a `prefix:local` tag into the `{namespace}local` form lxml uses."""
    prefix, local = tag.split(":", 1)
    return f"{{{NSMAP[prefix]}}}{local}"


def text_of(element: etree._Element) -> str:
    """Concatenate every w:t descendant, which is how a run's text is stored.

    Word splits a single sentence across several runs whenever formatting or
    spell-check state changes mid-sentence, so the text of a paragraph is only
    complete once every run is joined.
    """
    return "".join(node.text or "" for node in element.iter(qn("w:t")))
