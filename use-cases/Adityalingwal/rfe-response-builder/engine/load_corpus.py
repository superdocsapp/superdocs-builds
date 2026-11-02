from pathlib import Path

from engine.model import SourceSection
from engine.read_document import SUPPORTED_SUFFIXES, read_document
from engine.retrieve_petition_material import split_into_sections


def supported_files(folder: Path) -> list[Path]:
    return sorted(
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES
    )


def unsupported_files(folder: Path) -> list[str]:
    return sorted(
        f.name for f in folder.iterdir()
        if f.is_file()
        and not f.name.startswith(".")
        and f.suffix.lower() not in SUPPORTED_SUFFIXES
    )


def notice_file(notice_dir: Path) -> Path:
    files = supported_files(notice_dir)
    if len(files) != 1:
        raise ValueError(
            f"expected exactly one notice file in {notice_dir}, found "
            f"{len(files)} — pass the folder holding the single RFE notice "
            f"({', '.join(SUPPORTED_SUFFIXES)})"
        )
    return files[0]


def read_notice(notice_dir: Path) -> str:
    return read_document(notice_file(notice_dir))


def read_petition(petition_dir: Path) -> dict[str, str]:
    files = supported_files(petition_dir)
    if not files:
        raise ValueError(
            f"no petition documents found in {petition_dir} — the petition "
            f"folder must hold at least one document "
            f"({', '.join(SUPPORTED_SUFFIXES)})"
        )
    return {f.name: read_document(f) for f in files}


def petition_sections(petition: dict[str, str]) -> list[SourceSection]:
    sections: list[SourceSection] = []
    for name, text in petition.items():
        sections.extend(split_into_sections(name, text))
    return sections
