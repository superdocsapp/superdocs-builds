from __future__ import annotations

from pathlib import Path

from docx import Document


def read_docx_lines(
    path: str | Path,
) -> list[str]:
    """
    Read non-empty paragraph text from a DOCX
    while preserving document order.

    This is also our no-live-key local fallback
    for tests and graceful degradation.
    """

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"Input document not found: {path}"
        )

    if path.suffix.lower() != ".docx":
        raise ValueError(
            "Unsupported local input format: "
            f"{path.suffix or '(no extension)'}. "
            "Expected .docx."
        )

    document = Document(
        path
    )

    lines: list[str] = []

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()

        if text:
            lines.append(
                text
            )

    return lines