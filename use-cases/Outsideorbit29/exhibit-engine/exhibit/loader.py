"""Extract text from the mixed-format evidence pile.

The paralegal drops in whatever they have: .pdf, .docx, .md, .txt, .html. This
module reads each by extension with a tiny, dependency-light loader. PDFs use
``pypdfium2`` if present; .docx uses ``python-docx`` if present; plain text
formats are read directly. Files whose loader is unavailable raise a clear
error naming the missing package.
"""

from __future__ import annotations

import html.parser as _hp
from pathlib import Path

from .order import EvidenceItem

SUPPORTED = {".pdf", ".docx", ".doc", ".md", ".markdown", ".txt", ".html", ".htm", ".rtf"}


class _HtmlStripper(_hp.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def extract_text(path: str | Path) -> str:
    """Return the text content of one evidence file."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(
            f"Unsupported evidence format {suffix!r} for {p.name}. "
            f"Supported: {', '.join(sorted(SUPPORTED))}"
        )
    if suffix in {".md", ".markdown", ".txt"}:
        return p.read_text(encoding="utf-8", errors="replace")
    if suffix in {".html", ".htm", ".rtf"}:
        strip = _HtmlStripper()
        strip.feed(p.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(strip.parts)
    if suffix == ".docx":
        try:
            import docx  # python-docx
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError(
                "Reading .docx files requires 'python-docx'. Install it with "
                "`pip install python-docx`."
            ) from exc
        d = docx.Document(str(p))
        return "\n".join(par.text for par in d.paragraphs if par.text)
    if suffix == ".pdf":
        try:
            import pypdfium2
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError(
                "Reading .pdf files requires 'pypdfium2'. Install it with "
                "`pip install pypdfium2`."
            ) from exc
        pdf = pypdfium2.PdfDocument(str(p))
        try:
            chunks = []
            for page in pdf:
                tp = page.get_textpage()
                chunks.append(tp.get_text_range())
        finally:
            pdf.close()
        return "\n".join(chunks)
    if suffix == ".doc":
        raise ValueError(
            f".doc (legacy Word) is not supported for {p.name}; convert it to "
            ".docx or .txt and re-run."
        )
    raise ValueError(f"Unsupported format: {suffix}")  # pragma: no cover


def load_evidence(paths: list[str | Path]) -> list[EvidenceItem]:
    """Load every path in the pile into an ``EvidenceItem``."""
    items = []
    for path in paths:
        text = extract_text(path)
        items.append(EvidenceItem(source=str(path), text=text))
    return items
