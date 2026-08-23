from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from er_engine.issue import issue_letter, render_casefile
from er_engine.sequence import CaseFile, record_hearing_notes, record_meeting_notes
from er_engine.superdocs_flow import FakeDocs

app = FastAPI(title="HR ER letter engine")
CASES: dict[str, CaseFile] = {}
DOCS = FakeDocs()


class OpenBody(BaseModel):
    case_id: str
    employee_name: str
    employee_id: str


class NotesBody(BaseModel):
    notes: str
    employee_verbatim: str


class IssueBody(BaseModel):
    kind: str


@app.post("/cases")
def open_case(body: OpenBody) -> dict:
    c = CaseFile(case_id=body.case_id, employee_name=body.employee_name, employee_id=body.employee_id)
    c.open_case()
    CASES[c.case_id] = c
    return {"case_id": c.case_id, "done": sorted(c.done)}


@app.post("/cases/{case_id}/meeting-notes")
def meeting(case_id: str, body: NotesBody) -> dict:
    c = CASES[case_id]
    record_meeting_notes(c, body.notes, body.employee_verbatim)
    return {"done": sorted(c.done)}


@app.post("/cases/{case_id}/hearing-notes")
def hearing(case_id: str, body: NotesBody) -> dict:
    c = CASES[case_id]
    record_hearing_notes(c, body.notes, body.employee_verbatim)
    return {"done": sorted(c.done)}


@app.post("/cases/{case_id}/letters")
def letters(case_id: str, body: IssueBody) -> dict:
    c = CASES.get(case_id)
    if not c:
        raise HTTPException(404)
    result = issue_letter(c, body.kind, DOCS)  # type: ignore[arg-type]
    if result.get("refused"):
        raise HTTPException(409, detail=result["reason"])
    return result


@app.get("/cases/{case_id}/file")
def casefile(case_id: str) -> dict:
    c = CASES[case_id]
    return {"markdown": render_casefile(c), "chronology": c.chronology}
