"""Loads the field catalogue. Adding a figure or a document type is a change to the YAML."""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

FIELDMAP_PATH = Path(__file__).with_name("fieldmap.yaml")


@dataclass(slots=True)
class Field:
    id: str
    label: str
    kind: str
    appears_in: list[str]
    anchor: str | None = None
    table: str | None = None
    row: Any = None
    render: str | None = None
    spec: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DocumentSpec:
    name: str
    filename: str
    page_budget: int | None
    tables_must_not_reflow: list[str]


@dataclass(slots=True)
class ProtectedWording:
    document: str
    starts_with: str


@dataclass(slots=True)
class FieldMap:
    version: int
    documents: dict[str, DocumentSpec]
    fields: list[Field]
    protected: list[ProtectedWording]

    def by_id(self, field_id: str) -> Field | None:
        return next((f for f in self.fields if f.id == field_id), None)

    def for_document(self, document: str) -> list[Field]:
        return [f for f in self.fields if document in f.appears_in]

    def protected_for(self, document: str) -> list[ProtectedWording]:
        return [p for p in self.protected if p.document == document]


@lru_cache
def load_fieldmap(path: str | None = None) -> FieldMap:
    raw = yaml.safe_load(Path(path or FIELDMAP_PATH).read_text(encoding="utf-8"))
    return FieldMap(
        version=int(raw["version"]),
        documents={
            name: DocumentSpec(
                name=name,
                filename=spec["filename"],
                page_budget=spec.get("page_budget"),
                tables_must_not_reflow=spec.get("tables_must_not_reflow", []),
            )
            for name, spec in raw["documents"].items()
        },
        fields=[
            Field(
                id=f["id"],
                label=f["label"],
                kind=f["kind"],
                appears_in=f["appears_in"],
                anchor=f.get("anchor"),
                table=f.get("table"),
                row=f.get("row"),
                render=f.get("render"),
                spec=f,
            )
            for f in raw["fields"]
        ],
        protected=[
            ProtectedWording(document=p["document"], starts_with=p["starts_with"])
            for p in raw["protected_wording"]
        ],
    )
