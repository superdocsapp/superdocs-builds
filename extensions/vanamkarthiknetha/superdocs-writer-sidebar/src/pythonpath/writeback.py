"""Range-by-range write-back of approved SuperDocs changes into the live doc.

Each pending change carries the HTML it replaces (old_html) and the HTML it
becomes (new_html) — plain HTML on the jobs surface. We reduce old_html to its
plain-text paragraphs, locate them as ONE consecutive paragraph run in the open
document, and replace exactly that range with a style-preserving setString.

The honesty rule: a change whose original text cannot be found, or matches more
than one place, is SKIPPED and reported — never guessed at. Content outside a
matched range is never touched.
"""
import html as _html
import re

_BLOCK_BREAK = re.compile(r"</(?:p|h[1-6]|li|div|tr)\s*>|<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")


def _norm(text):
    """Whitespace-insensitive comparison form (HTML collapses whitespace)."""
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def html_paragraphs(markup):
    """Plain-text paragraphs of a block-level HTML fragment, in order."""
    paras = []
    for chunk in _BLOCK_BREAK.split(markup or ""):
        # inline tags (<b>, <span>...) vanish without leaving a space -
        # "<b>Friday</b>." must yield "Friday.", not "Friday ."; paragraph
        # boundaries were already handled by the block split above
        text = _norm(_html.unescape(_TAG.sub("", chunk)))
        if text:
            paras.append(text)
    return paras


def _paragraphs(doc):
    """Top-level text paragraphs of the document (table cells not included)."""
    out = []
    enum = doc.getText().createEnumeration()
    while enum.hasMoreElements():
        node = enum.nextElement()
        if node.supportsService("com.sun.star.text.Paragraph"):
            out.append(node)
    return out


def _find_runs(paras, wanted):
    """Start indexes where consecutive paragraphs equal `wanted` (normalized)."""
    texts = [_norm(p.getString()) for p in paras]
    n = len(wanted)
    return [i for i in range(len(texts) - n + 1) if texts[i:i + n] == wanted]


def apply_change(doc, change):
    """Apply one approved change. Returns (applied: bool, reason: str)."""
    old_paras = html_paragraphs(change.get("old_html"))
    new_paras = html_paragraphs(change.get("new_html"))
    if not old_paras:
        return False, "pure insertion (no anchor text) - apply manually"
    # fresh scan for every change: an earlier write-back moves paragraphs
    paras = _paragraphs(doc)
    hits = _find_runs(paras, old_paras)
    if not hits:
        return False, "original text not found (inside a table, or already changed)"
    if len(hits) > 1:
        return False, f"ambiguous ({len(hits)} identical matches)"
    first = paras[hits[0]]
    last = paras[hits[0] + len(old_paras) - 1]
    cursor = doc.getText().createTextCursorByRange(first.getStart())
    cursor.gotoRange(last.getEnd(), True)
    # setString keeps the range's styles; "\n" becomes a paragraph break
    cursor.setString("\n".join(new_paras))
    return True, "applied"


def apply_changes(doc, pending):
    """Apply approved changes range by range. Returns per-change result dicts."""
    return [{"change_id": change.get("change_id"), "applied": applied, "reason": reason}
            for change in pending
            for applied, reason in [apply_change(doc, change)]]


PARAGRAPH_BREAK = 0  # com.sun.star.text.ControlCharacter.PARAGRAPH_BREAK


def insert_paragraphs(doc, paras, at_range=None):
    """Insert plain-text paragraphs at at_range (default: end of document).

    Existing content is never modified: if the insertion point sits in a
    non-empty paragraph, a paragraph break is opened first. Returns the number
    of paragraphs inserted.
    """
    text = at_range.getText() if at_range is not None else doc.getText()
    if at_range is not None:
        cursor = text.createTextCursorByRange(at_range.getEnd())
    else:
        cursor = text.createTextCursor()
        cursor.gotoEnd(False)
    probe = text.createTextCursorByRange(cursor)
    probe.gotoStartOfParagraph(False)
    probe.gotoEndOfParagraph(True)
    if probe.getString().strip():
        text.insertControlCharacter(cursor, PARAGRAPH_BREAK, False)
    for i, para in enumerate(paras):
        if i:
            text.insertControlCharacter(cursor, PARAGRAPH_BREAK, False)
        text.insertString(cursor, para, False)
    return len(paras)


def summarize(results):
    """One status line, honest about anything skipped."""
    done = sum(1 for r in results if r["applied"])
    msg = f"Applied {done} of {len(results)} change(s) in place."
    skipped = [r["reason"] for r in results if not r["applied"]]
    if skipped:
        msg += (" Skipped (document NOT touched for these): "
                + "; ".join(skipped)
                + ". The approved SuperDocs copy still has them - export it if needed.")
    return msg
