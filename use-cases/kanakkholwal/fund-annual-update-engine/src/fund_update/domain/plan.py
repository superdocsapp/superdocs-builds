"""Turning last year's documents plus this year's figures into the smallest set of edits that works.

A field whose value did not move produces no edit. That is the whole point of the product: an
update should cost like an update.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from fund_update.domain.documents import DocumentView, current_value
from fund_update.domain.fieldmap import FieldMap


@dataclass(slots=True)
class Figure:
    field_id: str
    new_value: str
    source_document: str
    source_cell: str

    @property
    def citation(self) -> str:
        return f"{self.source_document} ({self.source_cell})"


@dataclass(slots=True)
class Edit:
    document: str
    field_id: str
    label: str
    old_value: str
    new_value: str
    citation: str
    anchor: str | None
    table: str | None
    row: object

    def instruction(self) -> str:
        """One targeted instruction. Deliberately narrow: it names the anchor, the old value and the
        new one, so the model has no room to reword anything around it."""
        where = (
            f"in the '{self.table}' table, row {self.row!r}"
            if self.table
            else f"where the document says '{self.anchor}'"
        )
        return (
            f"In the {self.document}, {where}, replace the value '{self.old_value}' with "
            f"'{self.new_value}'. Change only that value. Do not alter any other number, any "
            f"surrounding sentence, any heading, or the table's structure. Do not add or remove "
            f"table rows. Leave all legal wording exactly as it is."
        )


@dataclass(slots=True)
class Unresolved:
    field_id: str
    label: str
    reason: str
    citation: str


@dataclass(slots=True)
class Plan:
    edits: list[Edit] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)

    @property
    def operations(self) -> int:
        """One operation per document touched, not per edit: edits are batched per document."""
        return len({e.document for e in self.edits})

    def by_document(self) -> dict[str, list[Edit]]:
        out: dict[str, list[Edit]] = {}
        for edit in self.edits:
            out.setdefault(edit.document, []).append(edit)
        return out

    def summary(self) -> str:
        return (
            f"{len(self.edits)} edits across {self.operations} document(s), "
            f"{len(self.unchanged)} field(s) unchanged and skipped, "
            f"{len(self.unresolved)} unresolved"
        )


def read_figures(path: Path) -> dict[str, Figure]:
    if not path.is_file():
        raise FileNotFoundError(f"No data file at {path}. Fix: run `python make_fixtures.py` or pass --data.")
    figures: dict[str, Figure] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            figures[row["field_id"]] = Figure(
                field_id=row["field_id"],
                new_value=row["new_value"].strip(),
                source_document=row.get("source_document", "").strip(),
                source_cell=row.get("source_cell", "").strip(),
            )
    return figures


def write_reference_markdown(figures: dict[str, Figure], dest: Path) -> Path:
    """The API rejects .csv attachments, so the figures go up as a markdown table instead."""
    lines = [
        "# Approved figures for the 2025 annual update",
        "",
        "Every value below is final and approved. Use only these figures; compute nothing.",
        "",
        "| field_id | value | source document | source cell |",
        "| --- | --- | --- | --- |",
    ]
    for figure in figures.values():
        lines.append(
            f"| {figure.field_id} | {figure.new_value} | "
            f"{figure.source_document} | {figure.source_cell} |"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text('\n'.join(lines) + '\n', encoding="utf-8")
    return dest


def _normalise(value: str) -> str:
    return " ".join(value.replace("|", " | ").split()).strip().lower()


def _holding_complete(value: str) -> bool:
    """A holdings row needs both a name and a weight. Half a row is not a value."""
    parts = [p.strip() for p in value.split("|")]
    return len(parts) == 2 and bool(parts[0]) and bool(parts[1])


def build_plan(
    views: dict[str, DocumentView], figures: dict[str, Figure], fieldmap: FieldMap, *, sample: int = 0
) -> Plan:
    plan = Plan()
    considered = 0

    for spec_field in fieldmap.fields:
        if sample and considered >= sample:
            break

        figure = figures.get(spec_field.id)
        if figure is None:
            plan.unresolved.append(
                Unresolved(spec_field.id, spec_field.label, "no value supplied in the data file", "")
            )
            continue

        if spec_field.kind == "holding" and not _holding_complete(figure.new_value):
            plan.unresolved.append(
                Unresolved(
                    spec_field.id,
                    spec_field.label,
                    f"data file gives '{figure.new_value}' with no weight; a holdings row needs "
                    f"both a name and a weight, and the engine will not invent the missing half",
                    figure.citation,
                )
            )
            continue

        considered += 1
        touched_any = False

        for document in spec_field.appears_in:
            view = views.get(document)
            if view is None:
                continue
            old = current_value(view, fieldmap.documents[document], spec_field)
            if old is None:
                plan.unresolved.append(
                    Unresolved(
                        spec_field.id,
                        spec_field.label,
                        f"could not locate this field in the {document}",
                        figure.citation,
                    )
                )
                continue

            new = figure.new_value.replace("|", " | ")
            if spec_field.render:
                new = spec_field.render.format(value=new)
            if _normalise(old) == _normalise(new):
                continue

            touched_any = True
            plan.edits.append(
                Edit(
                    document=document,
                    field_id=spec_field.id,
                    label=spec_field.label,
                    old_value=old,
                    new_value=new,
                    citation=figure.citation,
                    anchor=spec_field.anchor,
                    table=spec_field.table,
                    row=spec_field.row,
                )
            )

        if not touched_any and not any(u.field_id == spec_field.id for u in plan.unresolved):
            plan.unchanged.append(spec_field.id)

    return plan
