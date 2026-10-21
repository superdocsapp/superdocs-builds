"""
Analyzes an HTML document's accessibility structure and produces a report
as data (a StructureReport dataclass, JSON-serializable), not prose. The
before/after report the task requires is literally two calls to
analyze() diffed against each other — it can't drift from what the
document actually contains, because it's derived from the document each
time, not written once and left stale.
"""
import re
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

_GENERIC_LINK_PHRASES = {
    "click here", "here", "link", "read more", "more", "this link",
    "click", "learn more", "see here", "go here",
}
_MANUAL_BULLET_RE = re.compile(r"^\s*([-*•]|\d+[.)])\s+\S")


@dataclass
class HeadingIssue:
    tag: str
    text: str
    reason: str


@dataclass
class TableIssue:
    index: int
    reason: str


@dataclass
class LinkIssue:
    text: str
    href: str
    reason: str


@dataclass
class ImageIssue:
    src: str
    reason: str


@dataclass
class StructureReport:
    heading_count: int = 0
    heading_issues: list[HeadingIssue] = field(default_factory=list)

    manual_bullet_paragraphs: int = 0
    real_list_count: int = 0

    table_count: int = 0
    table_issues: list[TableIssue] = field(default_factory=list)

    link_count: int = 0
    link_issues: list[LinkIssue] = field(default_factory=list)

    image_count: int = 0
    image_issues: list[ImageIssue] = field(default_factory=list)

    has_lang_attribute: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def total_issues(self) -> int:
        return (
            len(self.heading_issues)
            + self.manual_bullet_paragraphs
            + len(self.table_issues)
            + len(self.link_issues)
            + len(self.image_issues)
            + (0 if self.has_lang_attribute else 1)
        )


def analyze(html: str) -> StructureReport:
    soup = BeautifulSoup(html, "lxml")
    report = StructureReport()

    headings = soup.find_all(re.compile(r"^h[1-6]$"))
    report.heading_count = len(headings)
    prev_level = 0
    for h in headings:
        level = int(h.name[1])
        text = h.get_text(strip=True)
        if prev_level and level > prev_level + 1:
            report.heading_issues.append(
                HeadingIssue(
                    tag=h.name, text=text,
                    reason=f"skips from h{prev_level} to h{level} — no intermediate heading",
                )
            )
        prev_level = level
    if headings and int(headings[0].name[1]) != 1:
        report.heading_issues.append(
            HeadingIssue(
                tag=headings[0].name, text=headings[0].get_text(strip=True),
                reason="document's first heading is not h1",
            )
        )

    report.real_list_count = len(soup.find_all(["ul", "ol"]))
    for p in soup.find_all(["p", "div"]):
        if p.find_parent(["li"]):
            continue
        text = p.get_text()
        if _MANUAL_BULLET_RE.match(text):
            report.manual_bullet_paragraphs += 1

    tables = soup.find_all("table")
    report.table_count = len(tables)
    for i, table in enumerate(tables):
        has_th = table.find("th") is not None
        if not has_th:
            report.table_issues.append(TableIssue(index=i, reason="no <th> header cells found"))
        else:
            ths_without_scope = [th for th in table.find_all("th") if not th.get("scope")]
            if ths_without_scope:
                report.table_issues.append(
                    TableIssue(index=i, reason=f"{len(ths_without_scope)} <th> cell(s) missing a scope attribute")
                )

    links = soup.find_all("a", href=True)
    report.link_count = len(links)
    for a in links:
        text = a.get_text(strip=True).lower()
        if not text:
            report.link_issues.append(LinkIssue(text="", href=a["href"], reason="empty link text"))
        elif text in _GENERIC_LINK_PHRASES:
            report.link_issues.append(
                LinkIssue(text=text, href=a["href"], reason="generic link text doesn't describe the destination")
            )

    images = soup.find_all("img")
    report.image_count = len(images)
    for img in images:
        if not img.get("alt", "").strip():
            report.image_issues.append(ImageIssue(src=img.get("src", "(no src)"), reason="missing alt text"))

    html_tag = soup.find("html")
    report.has_lang_attribute = bool(html_tag and html_tag.get("lang", "").strip())

    return report


def diff_reports(before: StructureReport, after: StructureReport) -> dict:
    return {
        "heading_issues": {"before": len(before.heading_issues), "after": len(after.heading_issues)},
        "manual_bullet_paragraphs": {"before": before.manual_bullet_paragraphs, "after": after.manual_bullet_paragraphs},
        "real_list_count": {"before": before.real_list_count, "after": after.real_list_count},
        "table_issues": {"before": len(before.table_issues), "after": len(after.table_issues)},
        "link_issues": {"before": len(before.link_issues), "after": len(after.link_issues)},
        "image_issues": {"before": len(before.image_issues), "after": len(after.image_issues)},
        "has_lang_attribute": {"before": before.has_lang_attribute, "after": after.has_lang_attribute},
        "total_issues": {"before": before.total_issues, "after": after.total_issues},
    }


def residue_notes(after: StructureReport) -> list[str]:
    notes = []
    if after.image_issues:
        notes.append(
            f"{len(after.image_issues)} image(s) still lack alt text, or have AI-generated alt "
            f"text that was never confirmed by a human — alt text describes intent, and intent "
            f"can't be verified from pixels alone. Needs a human who knows what the image is for."
        )
    if after.link_issues:
        notes.append(
            f"{len(after.link_issues)} link(s) still have non-descriptive text after automated "
            f"rewriting — the AI's best guess at destination intent may not match what the "
            f"author meant. Needs a human to confirm or correct the wording."
        )
    if after.table_issues:
        notes.append(
            f"{len(after.table_issues)} table(s) still have header/scope issues — automatic "
            f"header detection is unreliable on tables with merged cells or ambiguous row/column "
            f"headers. Needs a human to confirm which cells are actually headers."
        )
    if not after.has_lang_attribute:
        notes.append(
            "No language attribute was set — the source document gave no reliable signal for "
            "which language/locale to declare. Needs a human to set it explicitly."
        )
    return notes


def validate_export_artifact(path: Path, format_name: str) -> dict:
    """Validate that an export is readable and has the expected container format."""
    if not path.is_file() or path.stat().st_size == 0:
        return {"valid": False, "reason": "missing or empty export"}
    if format_name == "pdf":
        content = path.read_bytes()
        valid = content.startswith(b"%PDF-") and b"%%EOF" in content[-1024:]
        return {
            "valid": valid,
            "reason": None if valid else "PDF signature or EOF marker missing",
        }
    if format_name == "docx":
        try:
            with zipfile.ZipFile(path) as archive:
                valid = "[Content_Types].xml" in archive.namelist() and "word/document.xml" in archive.namelist()
        except zipfile.BadZipFile:
            valid = False
        return {"valid": valid, "reason": None if valid else "DOCX package parts missing or ZIP is invalid"}
    return {"valid": False, "reason": f"unsupported export format: {format_name}"}