from dataclasses import dataclass

from docx import Document


@dataclass
class SectionDiffReport:
    unchanged_sections: list[str]
    changed_sections: list[str]
    expected_unchanged: list[str]
    expected_changed: list[str]

    @property
    def proof_passed(self) -> bool:
        unexpected_changes = set(self.changed_sections) - set(self.expected_changed)
        missing_changes = set(self.expected_changed) - set(self.changed_sections)
        unexpected_unchanged = set(self.expected_unchanged) - set(self.unchanged_sections)
        return not unexpected_changes and not missing_changes and not unexpected_unchanged


def extract_section_texts(docx_path: str, section_ids: list[str]) -> dict[str, str]:
    doc = Document(docx_path)
    texts: dict[str, list[str]] = {section_id: [] for section_id in section_ids}
    current_section: str | None = None

    for paragraph in doc.paragraphs:
        style_name = paragraph.style.name if paragraph.style else ""
        text = paragraph.text.strip()
        if not text:
            continue

        matched_section = next(
            (section_id for section_id in section_ids if text.startswith(section_id)),
            None,
        )
        if matched_section and ("Heading" in style_name or text.startswith(matched_section)):
            current_section = matched_section
            texts[current_section].append(text)
            continue

        if current_section:
            texts[current_section].append(text)

    return {section_id: "\n".join(parts).strip() for section_id, parts in texts.items()}


def compare_section_exports(
    previous_path: str,
    current_path: str,
    section_ids: list[str],
    expected_changed: list[str],
) -> SectionDiffReport:
    previous_texts = extract_section_texts(previous_path, section_ids)
    current_texts = extract_section_texts(current_path, section_ids)

    unchanged_sections = []
    changed_sections = []

    for section_id in section_ids:
        if previous_texts.get(section_id) == current_texts.get(section_id):
            unchanged_sections.append(section_id)
        else:
            changed_sections.append(section_id)

    expected_changed_set = set(expected_changed)
    expected_unchanged = [s for s in section_ids if s not in expected_changed_set]

    return SectionDiffReport(
        unchanged_sections=unchanged_sections,
        changed_sections=changed_sections,
        expected_unchanged=expected_unchanged,
        expected_changed=expected_changed,
    )
