"""
Text extraction for uploaded supporting documents.

Before this module, `arguments_from_free_text` (rfe.py) only ever
received text via `Path.read_text()` -- meaning a supporting document
had to already be a `.txt` file. Real immigration case files show up as
PDFs (scanned or generated) and Word documents far more often than
plain text, so restricting supporting-document uploads to `.txt` made
the tool feel more like a code demo than an actual legal workflow.

This module adds `.pdf` and `.docx` extraction as a thin layer IN FRONT
OF `arguments_from_free_text`, not a replacement for it: once text is
extracted, it goes through the exact same paragraph-splitting,
keyword-matching pipeline as a `.txt` upload always has. Every citation
`arguments_from_free_text` produces still traces to a real paragraph in
a real uploaded document -- extraction just widens what counts as
"a real uploaded document."

Deliberately conservative about failure: a corrupted, password-protected,
image-only (scanned with no text layer), or otherwise unextractable
file raises `DocumentExtractionError` with a clear, human-readable
message rather than silently producing empty text (which would make
that document invisibly vanish from matching with no indication why) or
crashing with a raw library exception a paralegal can't interpret.
"""
from __future__ import annotations

from pathlib import Path

SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".docx"}


class DocumentExtractionError(ValueError):
    """Raised with a human-readable message when a supporting document's
    text can't be extracted -- unsupported extension, corrupted file,
    password-protected PDF, or a PDF/DOCX with no extractable text
    (e.g. a scanned image with no OCR text layer)."""


def extract_text(path: Path) -> str:
    """Dispatches on file extension and returns extracted plain text.
    Raises `DocumentExtractionError` (never a raw library exception,
    never silent empty-string success) on anything that goes wrong."""
    ext = path.suffix.lower()
    if ext == ".txt":
        return _extract_txt(path)
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    raise DocumentExtractionError(
        f"Unsupported file type '{ext}' for '{path.name}' -- supported types are "
        f"{', '.join(sorted(SUPPORTED_EXTENSIONS))}."
    )


def _extract_txt(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise DocumentExtractionError(
            f"'{path.name}' is not valid UTF-8 text. If this is actually a PDF or Word "
            f"document, make sure it has the correct .pdf/.docx extension."
        ) from e


def _extract_pdf(path: Path) -> str:
    try:
        import pypdf
    except ImportError as e:
        raise DocumentExtractionError(
            "PDF extraction requires the 'pypdf' package, which is not installed in this "
            "environment. Install it (see requirements.txt) or upload a .txt/.docx file instead."
        ) from e

    try:
        reader = pypdf.PdfReader(str(path))
    except Exception as e:  # noqa: BLE001 - pypdf raises several distinct exception
        # types for malformed PDFs across versions; the point is to
        # surface one consistent, human-readable error regardless.
        raise DocumentExtractionError(f"Could not open '{path.name}' as a PDF: {e}") from e

    if reader.is_encrypted:
        # Attempt a blank-password unlock (common for PDFs "protected"
        # only against editing, not reading) before giving up -- but
        # never guess at a real password.
        try:
            reader.decrypt("")
        except Exception:
            pass
        if reader.is_encrypted:
            raise DocumentExtractionError(
                f"'{path.name}' is a password-protected PDF. Remove the password and "
                f"re-upload, or upload a .txt/.docx version instead."
            )

    pages_text = []
    for page in reader.pages:
        try:
            pages_text.append(page.extract_text() or "")
        except Exception as e:  # noqa: BLE001 - a single malformed page must not
            # abort extraction of the rest of the document.
            pages_text.append("")
    text = "\n\n".join(t for t in pages_text if t.strip())

    if not text.strip():
        raise DocumentExtractionError(
            f"No extractable text found in '{path.name}' -- this is usually a scanned "
            f"PDF with no text layer (an image, not text). Run OCR first, or upload a "
            f".txt/.docx version instead."
        )
    return text


def _extract_docx(path: Path) -> str:
    try:
        import docx
    except ImportError as e:
        raise DocumentExtractionError(
            "DOCX extraction requires the 'python-docx' package, which is not installed "
            "in this environment. Install it (see requirements.txt) or upload a .txt/.pdf "
            "file instead."
        ) from e

    try:
        document = docx.Document(str(path))
    except Exception as e:  # noqa: BLE001 - python-docx raises several distinct
        # exception types for malformed .docx files; one consistent
        # human-readable error regardless of which one.
        raise DocumentExtractionError(f"Could not open '{path.name}' as a Word document: {e}") from e

    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    # Also pull text out of tables -- supporting letters sometimes put
    # dates/figures in a table rather than body paragraphs.
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    paragraphs.append(cell.text)

    text = "\n\n".join(paragraphs)
    if not text.strip():
        raise DocumentExtractionError(
            f"No extractable text found in '{path.name}' -- the document appears to be empty."
        )
    return text
