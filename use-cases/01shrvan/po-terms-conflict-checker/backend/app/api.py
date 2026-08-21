"""HTTP surface for the conflict checker.

Same shape as the corrective-plan build: the analysis is produced first, a person decides on each
finding, and the letter is only released once every finding has been decided. Undecided is not
approved — a letter that silently dropped a contested point would concede it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from app.domain.clause import ClauseArea, Party
from app.domain.register import RegisterEntry, reconcile
from app.extraction.extractor import extract_positions, find_instruction_attempts
from app.governing import Playbook, SequenceEvent, analyse
from app.judging import HeuristicJudge
from app.letter import build_letter, letter_to_html
from app.memo import ConflictMemo, build_memo, memo_to_html

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "corpus"
RULES = ROOT / "rules"

# Only HTML is rendered locally. DOCX and PDF come from SuperDocs itself; accepting them here and
# returning HTML bytes would be a capability that is present and broken.
LOCAL_EXPORT_FORMATS = frozenset({"html"})
SUPERDOCS_EXPORT_FORMATS = frozenset({"docx", "pdf", "html", "markdown", "txt", "doc"})

Decision = Literal["pending", "approved", "rejected"]


class DocumentIn(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    text: str = Field(min_length=1)


class EventIn(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    on: date
    by: str
    note: str | None = None


class CompareRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    buyer: DocumentIn
    supplier: DocumentIn
    sequence: tuple[EventIn, ...] = ()
    doctrine: str = "last-shot-england"


class ExportRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    buyer: DocumentIn
    supplier: DocumentIn
    sequence: tuple[EventIn, ...] = ()
    doctrine: str = "last-shot-england"
    decisions: dict[str, Decision] = Field(default_factory=dict)
    document: Literal["memo", "letter"] = "letter"
    format: str = "html"
    to: str = "The supplier"
    from_: str = "The buyer"
    order_reference: str = "the order"


def create_app() -> FastAPI:
    app = FastAPI(title="PO Terms Conflict Checker")

    @app.get("/api/sample")
    def sample(pile: str = "pile-a") -> dict[str, Any]:
        folder = CORPUS / pile
        if not folder.is_dir():
            raise HTTPException(
                404,
                f"no sample pile named {pile!r}. Available: "
                f"{', '.join(sorted(p.name for p in CORPUS.iterdir() if p.is_dir()))}.",
            )
        buyer = _first_document(folder / "buyer")
        supplier = _first_document(folder / "supplier")
        return {
            "buyer": buyer,
            "supplier": supplier,
            # A plausible battle-of-the-forms sequence, editable by the caller. Dates drive the
            # doctrine, so they are shown rather than hidden.
            "sequence": [
                {"kind": "po_issued", "on": "2026-02-09", "by": "buyer"},
                {"kind": "acknowledgement_returned", "on": "2026-02-12", "by": "supplier"},
                {"kind": "goods_delivered", "on": "2026-02-26", "by": "supplier"},
                {"kind": "goods_accepted", "on": "2026-02-26", "by": "buyer"},
            ],
            "order_reference": buyer["name"].removesuffix(".txt"),
        }

    @app.get("/api/doctrines")
    def doctrines() -> dict[str, Any]:
        """The rule files on disk. A new jurisdiction is a file, not a deploy."""
        return {
            "doctrines": [
                {
                    "id": path.stem,
                    "name": Playbook.from_file(path).doctrine,
                    "summary": Playbook.from_file(path).summary,
                }
                for path in sorted(RULES.glob("*.json"))
            ]
        }

    @app.post("/api/compare")
    def compare(request: CompareRequest) -> dict[str, Any]:
        memo, entries, instructions = _analyse(request)
        return {
            "memo": _memo_json(memo),
            "instruction_findings": instructions,
            "review_items": [
                {"id": _item_id(section.area), "heading": section.heading,
                 "verdict": section.verdict, "state": "pending"}
                for section in (*memo.conflicts, *memo.silences)
            ],
            "entry_count": len(entries),
        }

    @app.post("/api/export")
    def export(request: ExportRequest) -> Response:
        if request.format not in SUPERDOCS_EXPORT_FORMATS:
            raise HTTPException(
                400,
                f"export failed: format {request.format!r} is not valid. Use "
                f"{_named(SUPERDOCS_EXPORT_FORMATS)}.",
            )
        if request.format not in LOCAL_EXPORT_FORMATS:
            raise HTTPException(
                501,
                f"export failed: this endpoint renders locally and produces "
                f"{_named(LOCAL_EXPORT_FORMATS)} only, so {request.format!r} is not available "
                f"here. SuperDocs produces {_named(SUPERDOCS_EXPORT_FORMATS)} from an approved "
                f"session — set SUPERDOCS_API_KEY and export through the live drafting path.",
            )

        memo, _, _ = _analyse(request)
        outstanding = (*memo.conflicts, *memo.silences)

        undecided = [
            section.heading
            for section in outstanding
            if request.decisions.get(_item_id(section.area), "pending") == "pending"
        ]
        if undecided:
            raise HTTPException(
                409,
                f"export refused: {len(undecided)} finding(s) are undecided — "
                f"{', '.join(undecided)}. Approve or reject each before producing the letter. "
                f"Undecided is not approved.",
            )

        if request.document == "memo":
            return Response(content=memo_to_html(memo), media_type="text/html")

        # Rejected findings are dropped from the letter but stay in the memo: the reviewer decided
        # not to raise them, not that they were never found.
        kept = memo.model_copy(
            update={
                "conflicts": tuple(
                    s for s in memo.conflicts
                    if request.decisions.get(_item_id(s.area)) == "approved"
                ),
                "silences": tuple(
                    s for s in memo.silences
                    if request.decisions.get(_item_id(s.area)) == "approved"
                ),
            }
        )
        letter = build_letter(
            kept,
            to=request.to,
            from_=request.from_,
            dated=date.today(),
            order_reference=request.order_reference,
        )
        return Response(content=letter_to_html(letter), media_type="text/html")

    static_dir = ROOT / "frontend" / "dist"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


app = create_app()


def _analyse(
    request: CompareRequest | ExportRequest,
) -> tuple[ConflictMemo, list[RegisterEntry], list[dict[str, str]]]:
    buyer_positions = extract_positions(
        document_id=request.buyer.name, text=request.buyer.text, party=Party.BUYER
    )
    supplier_positions = extract_positions(
        document_id=request.supplier.name, text=request.supplier.text, party=Party.SUPPLIER
    )

    judge = HeuristicJudge()
    entries: list[RegisterEntry] = []
    unaddressed: list[ClauseArea] = []
    for area in ClauseArea:
        entry = reconcile(area, buyer_positions.get(area), supplier_positions.get(area), judge)
        if entry is None:
            unaddressed.append(area)
        else:
            entries.append(entry)

    governing = None
    if request.sequence:
        path = RULES / f"{request.doctrine}.json"
        if not path.exists():
            raise HTTPException(
                404,
                f"no doctrine named {request.doctrine!r}. Available: "
                f"{', '.join(sorted(p.stem for p in RULES.glob('*.json')))}.",
            )
        try:
            events = [
                SequenceEvent(kind=e.kind, on=e.on, by=e.by, note=e.note)
                for e in request.sequence
            ]
        except ValueError as error:
            raise HTTPException(422, f"sequence rejected: {error}") from None
        governing = analyse(events, Playbook.from_file(path))

    memo = build_memo(
        buyer_document=request.buyer.name,
        supplier_document=request.supplier.name,
        entries=entries,
        unaddressed=unaddressed,
        governing=governing,
    )

    # Instructions found inside a source document are reported, never obeyed.
    instructions = [
        {"document": doc.name, "phrase": phrase, "quote": citation.quote}
        for doc in (request.buyer, request.supplier)
        for citation, phrase in find_instruction_attempts(document_id=doc.name, text=doc.text)
    ]
    return memo, entries, instructions


def _memo_json(memo: ConflictMemo) -> dict[str, Any]:
    def section(s) -> dict[str, Any]:
        return {
            "id": _item_id(s.area),
            "area": s.area,
            "heading": s.heading,
            "verdict": s.verdict,
            "buyer_says": list(s.buyer_says),
            "supplier_says": list(s.supplier_says),
            "silent_party": s.silent_party,
            "comment": s.comment,
        }

    return {
        "buyer_document": memo.buyer_document,
        "supplier_document": memo.supplier_document,
        "summary": memo.summary_line(),
        "conflicts": [section(s) for s in memo.conflicts],
        "silences": [section(s) for s in memo.silences],
        "agreements": [section(s) for s in memo.agreements],
        "unaddressed": list(memo.unaddressed),
        "governing": None
        if memo.governing is None
        else {
            "doctrine": memo.governing.doctrine,
            "rule_id": memo.governing.rule_id,
            "likely_to_govern": memo.governing.likely_to_govern,
            "conclusion": memo.governing.conclusion,
            "reasoning": memo.governing.reasoning,
            "prose": memo.governing.as_prose(),
            "is_inconclusive": memo.governing.is_inconclusive,
            "missing_to_decide": list(memo.governing.missing_to_decide),
        },
    }


def _item_id(area: ClauseArea) -> str:
    return f"area:{area.value}"


def _first_document(folder: Path) -> dict[str, str]:
    path = sorted(folder.iterdir())[0]
    return {"name": path.name, "text": path.read_text(encoding="utf-8")}


def _named(formats: frozenset[str]) -> str:
    return ", ".join(f"{value!r}" for value in sorted(formats))
