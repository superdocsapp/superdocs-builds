from pathlib import Path
from typing import Dict, List


SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
    ".docx",
}


def read_document(path: Path) -> str:
    """Read a supported document into plain text."""

    suffix = path.suffix.lower()

    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {suffix}. "
            f"Supported types: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    if suffix in {".txt", ".md"}:
        return path.read_text(
            encoding="utf-8",
            errors="replace",
        )

    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = []

        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append(f"[PAGE {page_number}]\n{text}")

        return "\n".join(pages)

    if suffix == ".docx":
        from docx import Document

        document = Document(str(path))
        return "\n".join(
            paragraph.text
            for paragraph in document.paragraphs
        )

    raise ValueError(f"Unsupported file type: {suffix}")


def ingest_directory(directory: str | Path) -> List[Dict]:
    """Read all supported documents from a directory."""

    directory = Path(directory)

    if not directory.exists():
        raise FileNotFoundError(
            f"Grant directory does not exist: {directory}"
        )

    documents = []

    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue

        content = read_document(path)

        documents.append(
            {
                "filename": path.name,
                "path": str(path),
                "extension": path.suffix.lower(),
                "content": content,
                "characters": len(content),
            }
        )

    return documents