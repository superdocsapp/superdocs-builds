from __future__ import annotations

import html as html_mod
import io
import re


def title_from_filename(filename: str) -> str:
    """Turn a filename into something readable enough to name a negotiation after.

    A deal named `Acme_Globex_MSA.docx` produces lines like "added X.docx to
    Acme_Globex_MSA.docx", which reads as a bug even though it is not. Strip the
    extension and the separators and the same line becomes "added X.docx to Acme
    Globex MSA". Purely cosmetic: the real filename is still stored on the document.
    """
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    words = [word for word in re.split(r"[_\-\s]+", stem) if word]
    if not words:
        return filename
    # Keep words that are already capitalised or acronyms (MSA, NDA, SOW) as they are;
    # only fix the ones that arrive all-lowercase.
    return " ".join(word if not word.islower() else word.capitalize() for word in words)


def extract_document_text(filename: str, raw: bytes) -> str:
    """Best-effort plain text for search indexing.

    Never raises: a document we cannot parse simply contributes no searchable text
    rather than breaking the whole search. Returning "" is honest -- the caller reports
    no hits for that file instead of guessing at its contents.
    """
    lower = filename.lower()
    try:
        if lower.endswith(".docx"):
            import docx

            document = docx.Document(io.BytesIO(raw))
            parts = [p.text for p in document.paragraphs if p.text.strip()]
            for table in document.tables:
                for row in table.rows:
                    parts.extend(cell.text for cell in row.cells if cell.text.strip())
            return "\n".join(parts)
        if lower.endswith((".html", ".htm")):
            text = raw.decode("utf-8", errors="replace")
            return html_mod.unescape(re.sub(r"<[^>]+>", " ", text)).strip()
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""
