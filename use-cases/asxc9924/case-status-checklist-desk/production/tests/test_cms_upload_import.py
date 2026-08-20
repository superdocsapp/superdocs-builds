import io
import json

import pytest


CSV_SAMPLE = """case_id,client_name,language,case_type,stage,document_name,document_form_type,document_received,document_due_date
CASE-2001,Aisha Karim,en,employment-based petition,documents_pending,Passport,certified copy,no,2026-10-01
CASE-2001,Aisha Karim,en,employment-based petition,documents_pending,Bank Statement,last 3 months,yes,
CASE-2002,Tomas Silva,pt,family petition,filed,,,,
"""

CSV_MISSING_COLUMN = """client_name,stage
Someone,filed
"""

CSV_WITH_BLANK_CASE_ID = """case_id,client_name,case_type,stage,document_name,document_form_type,document_received,document_due_date
CASE-3001,Real Case,family petition,filed,,,,
,Ghost Row,family petition,filed,,,,
"""


def test_csv_case_source_parses_multi_row_case(tmp_path):
    from case_status_desk.case_import import CsvFileCaseSource

    path = tmp_path / "cases.csv"
    path.write_text(CSV_SAMPLE)

    cases = CsvFileCaseSource(path).fetch_cases()
    by_id = {c.case_id: c for c in cases}

    assert set(by_id) == {"CASE-2001", "CASE-2002"}

    aisha = by_id["CASE-2001"]
    assert aisha.client_name == "Aisha Karim"
    assert aisha.client_language == "en"
    assert len(aisha.documents) == 2
    passport = next(d for d in aisha.documents if d.name == "Passport")
    assert passport.form_type == "certified copy"
    assert passport.received is False
    assert passport.due_date.isoformat() == "2026-10-01"
    bank = next(d for d in aisha.documents if d.name == "Bank Statement")
    assert bank.received is True

    tomas = by_id["CASE-2002"]
    assert tomas.documents == []  # fully documented case: no document rows


def test_csv_case_source_requires_core_columns(tmp_path):
    from case_status_desk.case_import import CsvFileCaseSource

    path = tmp_path / "bad.csv"
    path.write_text(CSV_MISSING_COLUMN)

    with pytest.raises(ValueError, match="missing required column"):
        CsvFileCaseSource(path).fetch_cases()


def test_csv_case_source_skips_blank_case_id_rows(tmp_path):
    from case_status_desk.case_import import CsvFileCaseSource

    path = tmp_path / "cases.csv"
    path.write_text(CSV_WITH_BLANK_CASE_ID)

    cases = CsvFileCaseSource(path).fetch_cases()
    assert len(cases) == 1
    assert cases[0].case_id == "CASE-3001"


def test_xlsx_case_source_matches_csv_semantics(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from case_status_desk.case_import import XlsxFileCaseSource

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["case_id", "client_name", "language", "case_type", "stage",
               "document_name", "document_form_type", "document_received", "document_due_date"])
    ws.append(["CASE-4001", "Nadia Hassan", "ar", "asylum", "documents_pending",
               "Identity Document", "certified translation", "no", "2026-11-15"])
    path = tmp_path / "cases.xlsx"
    wb.save(path)

    cases = XlsxFileCaseSource(path).fetch_cases()
    assert len(cases) == 1
    c = cases[0]
    assert c.case_id == "CASE-4001"
    assert c.client_language == "ar"
    assert len(c.documents) == 1
    assert c.documents[0].form_type == "certified translation"
    assert c.documents[0].due_date.isoformat() == "2026-11-15"


def test_xlsx_case_source_requires_core_columns(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from case_status_desk.case_import import XlsxFileCaseSource

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["client_name", "stage"])
    ws.append(["Someone", "filed"])
    path = tmp_path / "bad.xlsx"
    wb.save(path)

    with pytest.raises(ValueError, match="missing required column"):
        XlsxFileCaseSource(path).fetch_cases()


def test_csv_case_source_upserts_into_db(tmp_path):
    from case_status_desk.case_import import CsvFileCaseSource, sync_cases
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from case_status_desk.db import Base, CaseRecord

    engine = create_engine(f"sqlite:///{tmp_path}/csvimport.db", future=True)
    Session = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)

    path = tmp_path / "cases.csv"
    path.write_text(CSV_SAMPLE)
    count = sync_cases(CsvFileCaseSource(path), Session)
    assert count == 2

    with Session() as s:
        record = s.get(CaseRecord, "CASE-2001")
        assert record.client_name == "Aisha Karim"
        assert len(record.documents) == 2


def test_import_upload_endpoint_csv(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("STAFF_API_KEYS", "sk_test:Tester:admin")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/upload_test.db")
    monkeypatch.chdir(tmp_path)

    import importlib
    from case_status_desk import db as db_module
    importlib.reload(db_module)
    from case_status_desk import app as app_module
    importlib.reload(app_module)

    with TestClient(app_module.app) as client:
        files = {"file": ("export.csv", CSV_SAMPLE, "text/csv")}
        r = client.post("/v1/cases/import-upload", files=files,
                         headers={"Authorization": "Bearer sk_test"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["synced_count"] == 2
        assert body["source_format"] == "csv"

        # Confirm the uploaded case is now visible via the normal read path
        r2 = client.get("/v1/cases/CASE-2001", headers={"Authorization": "Bearer sk_test"})
        assert r2.status_code == 200
        case = r2.json()
        assert case["client_name"] == "Aisha Karim"
        assert case["fully_documented"] is False


def test_import_upload_endpoint_rejects_bad_extension(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("STAFF_API_KEYS", "sk_test:Tester:admin")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/upload_test2.db")
    monkeypatch.chdir(tmp_path)

    import importlib
    from case_status_desk import db as db_module
    importlib.reload(db_module)
    from case_status_desk import app as app_module
    importlib.reload(app_module)

    with TestClient(app_module.app) as client:
        files = {"file": ("export.txt", "not a real case file", "text/plain")}
        r = client.post("/v1/cases/import-upload", files=files,
                         headers={"Authorization": "Bearer sk_test"})
        assert r.status_code == 415


def test_import_upload_endpoint_rejects_missing_columns(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("STAFF_API_KEYS", "sk_test:Tester:admin")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/upload_test3.db")
    monkeypatch.chdir(tmp_path)

    import importlib
    from case_status_desk import db as db_module
    importlib.reload(db_module)
    from case_status_desk import app as app_module
    importlib.reload(app_module)

    with TestClient(app_module.app) as client:
        files = {"file": ("bad.csv", CSV_MISSING_COLUMN, "text/csv")}
        r = client.post("/v1/cases/import-upload", files=files,
                         headers={"Authorization": "Bearer sk_test"})
        assert r.status_code == 422
