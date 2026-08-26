"""Reading a fund document: the values that may change, and the wording that may not."""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document
from docx.table import Table

from fund_update.domain.fieldmap import DocumentSpec, FieldMap


def sha256_text(value: str) -> str:
    return hashlib.sha256(" ".join(value.split()).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class TableView:
    name: str
    headers: list[str]
    rows: list[list[str]]

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass(slots=True)
class DocumentView:
    """Everything the engine needs from a .docx, and nothing it does not."""

    name: str
    path: Path
    paragraphs: list[str]
    tables: dict[str, TableView] = field(default_factory=dict)

    def find_table(self, name: str) -> TableView | None:
        return self.tables.get(name.lower())

    def searchable_text(self) -> str:
        """Paragraphs and table cells as one string, for presence checks."""
        cells = [cell for table in self.tables.values() for row in table.rows for cell in row]
        return " ".join([*self.paragraphs, *cells])

    def protected_hashes(self, fieldmap: FieldMap) -> dict[str, str]:
        """Hash of each paragraph the refresh is forbidden to touch, keyed by its opening words."""
        out: dict[str, str] = {}
        for rule in fieldmap.protected_for(self.name):
            for para in self.paragraphs:
                if para.startswith(rule.starts_with):
                    out[rule.starts_with] = sha256_text(para)
                    break
        return out

    def layout_metrics(self) -> dict[str, int]:
        """Cheap structural fingerprint. Real page count comes from the exported PDF."""
        return {
            "paragraphs": len(self.paragraphs),
            "characters": sum(len(p) for p in self.paragraphs),
            "tables": len(self.tables),
            **{f"rows:{name}": t.row_count for name, t in sorted(self.tables.items())},
        }


def _table_name(doc, table: Table) -> str:
    """python-docx gives tables no name, so the preceding Heading 2 is used as the label."""
    body = list(doc.element.body)
    try:
        index = body.index(table._element)
    except ValueError:
        return ""
    for element in reversed(body[:index]):
        if element.tag.endswith("}p"):
            text = "".join(node.text or "" for node in element.iter() if node.tag.endswith("}t"))
            if text.strip():
                return text.strip()
    return ""


def read_document(name: str, path: Path) -> DocumentView:
    doc = Document(str(path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    tables: dict[str, TableView] = {}
    for table in doc.tables:
        label = _table_name(doc, table).lower()
        cells = [[c.text.strip() for c in row.cells] for row in table.rows]
        if not cells:
            continue
        tables[label] = TableView(name=label, headers=cells[0], rows=cells[1:])

    return DocumentView(name=name, path=path, paragraphs=paragraphs, tables=tables)


def read_set(baseline_dir: Path, fieldmap: FieldMap) -> dict[str, DocumentView]:
    views: dict[str, DocumentView] = {}
    for name, spec in fieldmap.documents.items():
        path = baseline_dir / spec.filename
        if not path.is_file():
            raise FileNotFoundError(
                f"{spec.filename} is missing from {baseline_dir}. "
                f"Fix: run `python make_fixtures.py` to build the sample document set."
            )
        views[name] = read_document(name, path)
    return views


_LABEL_VALUE = re.compile(r"^(?P<label>[^:]+):\s*(?P<value>.+)$")


def current_value(view: DocumentView, spec: DocumentSpec, field_) -> str | None:
    """The value a field holds today, or None when this document does not carry it."""
    if field_.table:
        table = view.find_table(field_.table)
        if table is None:
            return None
        if isinstance(field_.row, int):
            index = field_.row - 1
            if 0 <= index < table.row_count:
                return " | ".join(table.rows[index][1:])
            return None
        for row in table.rows:
            if row and row[0].strip() == str(field_.row):
                return row[1] if len(row) > 1 else None
        return None

    if not field_.anchor:
        return None

    for table in view.tables.values():
        for row in table.rows:
            if row and row[0].strip().lower() == field_.anchor.lower():
                return row[1] if len(row) > 1 else None

    for para in view.paragraphs:
        if field_.anchor.lower() in para.lower():
            match = _LABEL_VALUE.match(para)
            if match and field_.anchor.lower() in match.group("label").lower():
                return match.group("value").strip()
            trailing = para[para.lower().index(field_.anchor.lower()) + len(field_.anchor) :]
            cleaned = trailing.strip(" :.")
            if cleaned:
                return cleaned
    return None
