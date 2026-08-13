import json
import os


class Manifest:
    def __init__(self, filepath: str):
        with open(filepath, "r") as f:
            self.data = json.load(f)

    @property
    def sections(self) -> dict:
        return self.data.get("sections", {})

    def get_all_sources(self) -> set[str]:
        sources: set[str] = set()
        for data in self.sections.values():
            for source in data.get("sources", []):
                sources.add(source)
        return sources

    def get_all_section_ids(self) -> list[str]:
        return list(self.sections.keys())

    def get_affected_sections(self, changed_sources: set[str]) -> list[tuple[str, str, list[str]]]:
        affected = []
        for section, data in self.sections.items():
            section_sources = data.get("sources", [])
            if any(src in changed_sources for src in section_sources):
                affected.append((section, data["title"], section_sources))
        return affected


def detect_changed_sources(
    sources: set[str],
    old_hashes: dict[str, str],
    new_hashes: dict[str, str],
) -> set[str]:
    changed = set()
    for source in sources:
        if new_hashes.get(source) != old_hashes.get(source):
            changed.add(source)
    return changed


def select_upload_target(final_path: str, shell_path: str) -> str:
    if os.path.exists(final_path):
        return final_path
    return shell_path
