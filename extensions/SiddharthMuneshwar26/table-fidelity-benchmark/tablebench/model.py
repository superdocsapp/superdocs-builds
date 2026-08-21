"""Canonical table model.

One grid representation that the generator, the DOCX extractor and the HTML
extractor all produce. Comparison happens between two of these and never
between two file formats directly -- that is what lets the benchmark say
*where* fidelity was lost (ingest, edit, or export) instead of only that it was.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Cell:
    """One anchor cell. Cells covered by a span are not repeated."""

    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    paragraphs: list[str] = field(default_factory=list)
    alignment: str | None = None
    shading: str | None = None          # fill colour, upper hex, no '#'
    valign: str | None = None
    width_dxa: int | None = None
    text_direction: str | None = None
    borders: dict[str, str] = field(default_factory=dict)
    borders_declared: dict[str, str] = field(default_factory=dict)
    """Borders written on the cell itself, before table-level inheritance.

    Kept apart from the resolved set because an interior rule is shared by two
    cells: when they disagree, the one that declared it explicitly is the one
    that was meant."""
    nested: list["Table"] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.paragraphs)

    @property
    def is_merged(self) -> bool:
        return self.row_span > 1 or self.col_span > 1

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["nested"] = [t.to_dict() for t in self.nested]
        return d


@dataclass
class Table:
    n_rows: int = 0
    n_cols: int = 0
    cells: list[Cell] = field(default_factory=list)
    col_widths: list[int] = field(default_factory=list)
    layout: str | None = None           # 'fixed' | 'autofit'
    header_rows: list[int] = field(default_factory=list)   # w:tblHeader rows

    def cell_at(self, row: int, col: int) -> Cell | None:
        """The anchor covering (row, col), span-aware."""
        for c in self.cells:
            if (
                c.row <= row < c.row + c.row_span
                and c.col <= col < c.col + c.col_span
            ):
                return c
        return None

    def occupancy(self) -> dict[tuple[int, int], tuple[int, int]]:
        """(row, col) -> anchor coordinate. The topology fingerprint."""
        occ: dict[tuple[int, int], tuple[int, int]] = {}
        for c in self.cells:
            for r in range(c.row, c.row + c.row_span):
                for k in range(c.col, c.col + c.col_span):
                    occ[(r, k)] = (c.row, c.col)
        return occ

    def anchors(self) -> dict[tuple[int, int], Cell]:
        return {(c.row, c.col): c for c in self.cells}

    def border_edges(self) -> dict[tuple[str, int, int], str]:
        """Every drawn rule, keyed by its position in the grid.

        Interior edges are shared: the line between two cells can be declared
        as one cell's bottom or the next cell's top, and the document looks
        identical either way. Comparing cells would call that a difference.
        Comparing edges compares what is actually drawn.

        ('h', r, c) is the horizontal rule above row r spanning column c.
        ('v', r, c) is the vertical rule left of column c on row r.
        """
        edges: dict[tuple[str, int, int], str] = {}
        rank: dict[tuple[int, int, int], tuple[int, int]] = {}

        def claim(key, cell: "Cell", edge: str) -> None:
            spec = cell.borders.get(edge)
            if not spec:
                return
            # An explicitly declared border outranks an inherited one; between
            # two of the same kind the heavier rule wins. Without a rule here
            # the winner would depend on cell ordering, which would make the
            # same document compare differently against itself.
            declared = 1 if edge in cell.borders_declared else 0
            try:
                weight = int(spec.split("/")[1] or 0)
            except (IndexError, ValueError):
                weight = 0
            score = (declared, weight)
            if key not in edges or score > rank[key]:
                edges[key] = spec
                rank[key] = score

        for cell in self.cells:
            for r in range(cell.row, cell.row + cell.row_span):
                claim(("v", r, cell.col), cell, "left")
                claim(("v", r, cell.col + cell.col_span), cell, "right")
            for k in range(cell.col, cell.col + cell.col_span):
                claim(("h", cell.row, k), cell, "top")
                claim(("h", cell.row + cell.row_span, k), cell, "bottom")
        return edges

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_rows": self.n_rows,
            "n_cols": self.n_cols,
            "col_widths": self.col_widths,
            "layout": self.layout,
            "header_rows": self.header_rows,
            "cells": [c.to_dict() for c in self.cells],
        }


@dataclass
class Document:
    """Just the tables. Prose between tables is captured as a flat list so the
    invariance check can prove untouched body text did not move either."""

    tables: list[Table] = field(default_factory=list)
    body_paragraphs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tables": [t.to_dict() for t in self.tables],
            "body_paragraphs": self.body_paragraphs,
        }
