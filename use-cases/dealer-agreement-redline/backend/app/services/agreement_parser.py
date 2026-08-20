from pathlib import Path

from docx import Document


def extract_docx_sections(file_path: str | Path) -> list[dict]:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Document not found: {path}"
        )

    document = Document(path)

    sections: list[dict] = []
    current_section: dict | None = None

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()

        if not text:
            continue

        # Our test documents use Heading 2 for sections.
        if paragraph.style.name.startswith("Heading 2"):
            if current_section:
                sections.append(current_section)

            current_section = {
                "section": text,
                "text": "",
            }

        elif current_section:
            if current_section["text"]:
                current_section["text"] += "\n"

            current_section["text"] += text

    if current_section:
        sections.append(current_section)

    return sections