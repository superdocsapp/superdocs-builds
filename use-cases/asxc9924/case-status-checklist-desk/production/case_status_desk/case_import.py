"""
Adapter interface for importing case data from a real case-management
system (CMS), replacing the sample-data seed script for production use.

Implement `CaseSource.fetch_cases()` for whatever your firm actually
uses (Clio, INSZoom, a custom database, a CSV export job, etc.) and
point `scripts/import_cases.py` at it via IMPORT_ADAPTER. This keeps
db.py and service.py completely unaware of where case data comes from.

Ship two adapters out of the box:
  - JsonFileCaseSource   -- reads the same shape as data/sample_cases.json
                            (used for local dev / the CLI sample path)
  - HttpCaseSource       -- generic REST pull, for CMS's that expose a
                            JSON case-list endpoint (adjust field mapping
                            in `_map()` to match your CMS's actual schema)

Neither of these is a real, tested integration with any specific vendor
CMS -- that mapping step (`_map()`) is exactly the part every firm's
adapter will need to customize, since case-management systems don't
share a common schema. Treat this file as a template, not a finished
integration.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

import requests


@dataclass
class ImportedDocument:
    name: str
    form_type: str
    received: bool
    due_date: Optional[date] = None


@dataclass
class ImportedCase:
    case_id: str
    client_name: str
    client_language: str
    case_type: str
    stage: str
    documents: list[ImportedDocument]


class CaseSource(ABC):
    """Implement this against your real CMS."""

    @abstractmethod
    def fetch_cases(self) -> list[ImportedCase]:
        ...


class JsonFileCaseSource(CaseSource):
    """Reads the flat JSON shape used by data/sample_cases.json. Fine for
    local dev; for production, point at your real CMS export instead."""

    def __init__(self, path: Path):
        self.path = path

    def fetch_cases(self) -> list[ImportedCase]:
        raw = json.loads(self.path.read_text())
        return [self._map(item) for item in raw]

    @staticmethod
    def _map(item: dict[str, Any]) -> ImportedCase:
        return ImportedCase(
            case_id=item["case_id"],
            client_name=item["client_name"],
            client_language=item.get("language", "en"),
            case_type=item["case_type"],
            stage=item["stage"],
            documents=[
                ImportedDocument(
                    name=d["name"],
                    form_type=d["form_type"],
                    received=d.get("received", False),
                    due_date=date.fromisoformat(d["due_date"]) if d.get("due_date") else None,
                )
                for d in item.get("required_documents", [])
            ],
        )


class CsvFileCaseSource(CaseSource):
    """Reads case data from a CSV export -- the one format every CMS can
    produce, so this works regardless of which specific system a firm
    uses (Clio, Docketwise, INSZoom, MyCase, a custom CRM, whatever).

    A firm exports their case list to CSV from their existing CMS and
    uploads it here instead of us needing a live API integration with
    their specific vendor. This is the practical answer to "which CMS
    does the mapping need to target" -- it targets a documented column
    shape instead of a vendor's specific schema.

    Expected columns (case-insensitive; extra columns are ignored):
        case_id, client_name, language, case_type, stage,
        document_name, document_form_type, document_received, document_due_date

    One row per (case, required document) pair -- a case with 3 required
    documents appears as 3 rows sharing the same case_id/client_name/etc.
    A case with zero required documents (fully filed, nothing outstanding)
    appears as a single row with the document_* columns left blank.
    """

    REQUIRED_COLUMNS = {"case_id", "client_name", "case_type", "stage"}

    def __init__(self, path: Path):
        self.path = path

    def fetch_cases(self) -> list[ImportedCase]:
        import csv as _csv

        with self.path.open(newline="", encoding="utf-8-sig") as f:
            reader = _csv.DictReader(f)
            if reader.fieldnames is None:
                raise ValueError("CSV file has no header row")
            headers = {h.strip().lower() for h in reader.fieldnames}
            missing = self.REQUIRED_COLUMNS - headers
            if missing:
                raise ValueError(
                    f"CSV is missing required column(s): {', '.join(sorted(missing))}. "
                    f"Required: {', '.join(sorted(self.REQUIRED_COLUMNS))}"
                )
            rows = [{k.strip().lower(): (v or "").strip() for k, v in row.items()} for row in reader]

        return self._rows_to_cases(rows)

    @staticmethod
    def _rows_to_cases(rows: list[dict[str, str]]) -> list[ImportedCase]:
        by_case: dict[str, ImportedCase] = {}
        for row in rows:
            case_id = row.get("case_id", "")
            if not case_id:
                continue  # skip blank/malformed rows rather than crash the whole import
            if case_id not in by_case:
                by_case[case_id] = ImportedCase(
                    case_id=case_id,
                    client_name=row.get("client_name", ""),
                    client_language=row.get("language") or "en",
                    case_type=row.get("case_type", ""),
                    stage=row.get("stage", ""),
                    documents=[],
                )
            doc_name = row.get("document_name", "")
            if doc_name:
                due_raw = row.get("document_due_date", "")
                by_case[case_id].documents.append(ImportedDocument(
                    name=doc_name,
                    form_type=row.get("document_form_type", ""),
                    received=row.get("document_received", "").lower() in ("true", "yes", "1", "received"),
                    due_date=date.fromisoformat(due_raw) if due_raw else None,
                ))
        return list(by_case.values())


class XlsxFileCaseSource(CaseSource):
    """Same column shape and semantics as CsvFileCaseSource, but reads an
    .xlsx export instead of a .csv one -- some CMS's export Excel by
    default. Requires openpyxl (already a transitive need for many
    office-adjacent stacks; add it to requirements.txt if not present)."""

    def __init__(self, path: Path, sheet_name: Optional[str] = None):
        self.path = path
        self.sheet_name = sheet_name

    def fetch_cases(self) -> list[ImportedCase]:
        try:
            import openpyxl
        except ImportError as exc:
            raise ImportError(
                "XlsxFileCaseSource requires openpyxl. Install it with "
                "`pip install openpyxl` or use CsvFileCaseSource instead."
            ) from exc

        wb = openpyxl.load_workbook(self.path, read_only=True, data_only=True)
        ws = wb[self.sheet_name] if self.sheet_name else wb.active
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            raise ValueError("Excel sheet has no header row")
        headers = [str(h).strip().lower() if h is not None else "" for h in header_row]

        missing = CsvFileCaseSource.REQUIRED_COLUMNS - set(headers)
        if missing:
            raise ValueError(
                f"Excel sheet is missing required column(s): {', '.join(sorted(missing))}. "
                f"Required: {', '.join(sorted(CsvFileCaseSource.REQUIRED_COLUMNS))}"
            )

        rows: list[dict[str, str]] = []
        for values in rows_iter:
            row = {}
            for h, v in zip(headers, values):
                if not h:
                    continue
                row[h] = "" if v is None else str(v).strip()
            rows.append(row)

        return CsvFileCaseSource._rows_to_cases(rows)


class HttpCaseSource(CaseSource):
    """Generic REST pull for a CMS that exposes a JSON case-list
    endpoint. You MUST customize `_map()` below to match your CMS's
    actual field names -- this is a starting point, not a working
    integration for any specific vendor.
    """

    def __init__(self, base_url: str, api_key: str, timeout_s: float = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s

    def fetch_cases(self) -> list[ImportedCase]:
        resp = requests.get(
            f"{self.base_url}/cases",
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return [self._map(item) for item in resp.json()]

    @staticmethod
    def _map(item: dict[str, Any]) -> ImportedCase:
        # CUSTOMIZE: this mapping assumes field names that will not match
        # your real CMS. Adjust every .get()/[] access below before use.
        raise NotImplementedError(
            "HttpCaseSource._map() must be customized for your CMS's actual "
            "field names before this adapter can be used against a real system."
        )


def sync_cases(source: CaseSource, db_session_factory) -> int:
    """Upserts every case from `source` into the database. Returns the
    number of cases synced. Deliberately DB-shape-agnostic beyond what
    db.py already exposes, so this can be called from a script or a
    scheduled job either one."""
    from .db import CaseRecord, DocumentRequirement

    cases = source.fetch_cases()
    count = 0
    with db_session_factory() as db:
        for imported in cases:
            record = db.get(CaseRecord, imported.case_id)
            if record is None:
                record = CaseRecord(case_id=imported.case_id)
                db.add(record)
            record.client_name = imported.client_name
            record.client_language = imported.client_language
            record.case_type = imported.case_type
            record.stage = imported.stage

            record.documents.clear()
            for doc in imported.documents:
                record.documents.append(
                    DocumentRequirement(
                        name=doc.name, form_type=doc.form_type,
                        received=doc.received, due_date=doc.due_date,
                    )
                )
            count += 1
        db.commit()
    return count
