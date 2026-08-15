"""
Document ingestion: turns the raw source .txt files into paragraph-indexed
Document objects that carry full citation metadata (source id, title,
author/org, date, paragraph number) alongside the verbatim paragraph text.

Every downstream module quotes from these objects, never from the raw file,
so a citation always traces back to (source_id, paragraph_number) and the
quoted text is always a byte-for-byte substring of what's stored here.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

SOURCES_DIR = Path(__file__).parent / "sources"


@dataclass
class Paragraph:
    source_id: str
    number: int
    text: str

    def citation(self):
        return f"{self.source_id} ¶{self.number}"


@dataclass
class SourceDocument:
    source_id: str
    title: str
    author_or_org: str
    date: str
    filename: str
    paragraphs: list = field(default_factory=list)

    def full_citation(self):
        return f"{self.author_or_org}, “{self.title}” ({self.date})"


# Metadata describing each source file. This is the only place a human
# transcribes bibliographic info -- everything downstream reads paragraph
# text out of the files themselves, never retypes it.
SOURCE_METADATA = [
    {
        "source_id": "SRC-A",
        "filename": "source_A_ngo_report.txt",
        "title": "State Response to Threats Against Labor Organizers: Annual Report 2025",
        "author_or_org": "Civil Liberties Watch Salvarion",
        "date": "March 2025",
    },
    {
        "source_id": "SRC-B",
        "filename": "source_B_news_article.txt",
        "title": "Union Hall Attacked in Rosemont, Organizers Say Police Slow to Act",
        "author_or_org": "Salvarion Daily Post",
        "date": "16 June 2024",
    },
    {
        "source_id": "SRC-C",
        "filename": "source_C_country_backgrounder.txt",
        "title": "Salvarion Country Conditions Backgrounder, 2025 Edition",
        "author_or_org": "Meridian Country Research Group",
        "date": "2025",
    },
    {
        "source_id": "SRC-D",
        "filename": "source_D_expert_declaration.txt",
        "title": "Declaration of Dr. Elena Voss",
        "author_or_org": "Dr. Elena Voss, Dept. of Comparative Politics, Fictional University of Meridian",
        "date": "2025",
    },
]

_PARA_RE = re.compile(r"^\[(\d+)\]\s*(.*)$")


def _parse_paragraphs(source_id, raw_text):
    """Paragraphs in the source files are marked '[N] text...' and may wrap
    onto following lines until the next '[N+1]' marker or a blank line
    followed by end of paragraph block. We rejoin wrapped lines."""
    paragraphs = []
    current_num = None
    current_lines = []

    def flush():
        if current_num is not None:
            text = " ".join(l.strip() for l in current_lines if l.strip())
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                paragraphs.append(Paragraph(source_id, current_num, text))

    for line in raw_text.splitlines():
        m = _PARA_RE.match(line.strip())
        if m:
            flush()
            current_num = int(m.group(1))
            current_lines = [m.group(2)]
        elif current_num is not None:
            if line.strip() == "":
                continue
            current_lines.append(line)
    flush()
    return paragraphs


def load_all_sources():
    docs = []
    for meta in SOURCE_METADATA:
        path = SOURCES_DIR / meta["filename"]
        raw = path.read_text()
        paras = _parse_paragraphs(meta["source_id"], raw)
        docs.append(SourceDocument(
            source_id=meta["source_id"],
            title=meta["title"],
            author_or_org=meta["author_or_org"],
            date=meta["date"],
            filename=meta["filename"],
            paragraphs=paras,
        ))
    return docs


if __name__ == "__main__":
    for doc in load_all_sources():
        print(f"{doc.source_id}: {len(doc.paragraphs)} paragraphs — {doc.full_citation()}")
