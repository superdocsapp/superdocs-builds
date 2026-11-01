from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from soc2_index.identity import parse_row_id
from soc2_index.render import COLUMNS

EMPTY_SOURCE = {"—", "–", "-", "none", "", "—".strip()}


def strip_sd_attrs(html: str) -> str:
    out = re.sub(r'\sdata-chunk-id="[^"]*"', "", html)
    out = re.sub(r'\sdata-section-id="[^"]*"', "", out)
    return out


@dataclass
class ParsedRow:
    row_id: str
    tr_chunk_id: str | None
    data_row_id: str | None
    cells: list[str]
    dangling: bool = False
    unparseable: bool = False


@dataclass
class ParsedIndex:
    rows: list[ParsedRow] = field(default_factory=list)
    row_chunk_map: dict[str, str] = field(default_factory=dict)
    data_row_id_survived: bool = False
    dangling: list[str] = field(default_factory=list)
    invented: list[str] = field(default_factory=list)
    html_missing_gaps: list[str] = field(default_factory=list)
    overreach: list[str] = field(default_factory=list)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict] = []
        self._table: dict | None = None
        self._in_thead = False
        self._in_tbody = False
        self._in_tr = False
        self._in_th = False
        self._in_td = False
        self._cell_parts: list[str] = []
        self._row_cells: list[str] = []
        self._row_attrs: dict[str, str] = {}
        self._thead_labels: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k: (v or "") for k, v in attrs}
        if tag == "table":
            self._table = {
                "attrs": ad,
                "thead": [],
                "rows": [],
            }
            self.tables.append(self._table)
        elif tag == "thead":
            self._in_thead = True
        elif tag == "tbody":
            self._in_tbody = True
        elif tag == "tr" and self._table is not None:
            self._in_tr = True
            self._row_cells = []
            self._row_attrs = ad
        elif tag == "th" and self._in_tr:
            self._in_th = True
            self._cell_parts = []
        elif tag == "td" and self._in_tr:
            self._in_td = True
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "th" and self._in_th:
            self._in_th = False
            self._thead_labels.append("".join(self._cell_parts).strip())
        elif tag == "td" and self._in_td:
            self._in_td = False
            self._row_cells.append("".join(self._cell_parts).strip())
        elif tag == "tr" and self._in_tr:
            self._in_tr = False
            if self._table is None:
                return
            if self._in_thead:
                if self._thead_labels:
                    self._table["thead"] = list(self._thead_labels)
                self._thead_labels = []
            else:
                self._table["rows"].append({"attrs": dict(self._row_attrs), "cells": list(self._row_cells)})
            self._row_cells = []
        elif tag == "thead":
            self._in_thead = False
        elif tag == "tbody":
            self._in_tbody = False
        elif tag == "table":
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._in_th or self._in_td:
            self._cell_parts.append(data)


def _is_empty_source(value: str) -> bool:
    return value.strip() in EMPTY_SOURCE or value.strip() in {"—", "–", "-", "none"}


def _identity(attrs: dict[str, str], cells: list[str]) -> tuple[str | None, str | None, bool]:
    """Returns (row_id, data_row_id_attr, unparseable)."""
    attr = attrs.get("data-row-id")
    if attr and attr != "placeholder" and parse_row_id(attr):
        return attr, attr, False
    if len(cells) < 7:
        return None, attr, True
    control = cells[0].strip()
    status = cells[2].strip().lower()
    source = cells[6].strip()
    if status == "gap":
        if not control:
            return None, attr, True
        return f"{control}::gap::none", attr, False
    if status == "present":
        if _is_empty_source(source):
            return None, attr, True
        return f"{control}::present::{source}", attr, False
    return None, attr, True


def parse(html: str, files: list[dict] | None = None, canonical_ids: list[str] | None = None) -> ParsedIndex:
    parser = _TableParser()
    parser.feed(html)
    master = None
    for table in parser.tables:
        labels = [re.sub(r"\s+", " ", x) for x in table.get("thead") or []]
        if labels[:9] == COLUMNS:
            master = table
            break
    result = ParsedIndex()
    if master is None:
        return result
    by_path = {f["relative_path"]: f for f in (files or []) if "relative_path" in f}
    survived = True
    had_rows = False
    for raw in master["rows"]:
        cells = raw["cells"]
        if len(cells) == 1 and "NO ROWS YET" in (cells[0] or ""):
            continue
        attrs = raw["attrs"]
        tr_chunk = attrs.get("data-chunk-id")
        rid, attr, unparseable = _identity(attrs, cells)
        had_rows = True
        if attr is None or not parse_row_id(attr or ""):
            survived = False
        if unparseable or not rid:
            result.overreach.append("unmapped_chunk" if not tr_chunk else f"unparseable:{tr_chunk}")
            result.rows.append(
                ParsedRow(
                    row_id="",
                    tr_chunk_id=tr_chunk,
                    data_row_id=attr,
                    cells=cells,
                    unparseable=True,
                )
            )
            continue
        dangling = False
        if "::present::" in rid:
            path = rid.split("::", 2)[2]
            rec = by_path.get(path)
            sha_cell = cells[7].strip() if len(cells) > 7 else ""
            if rec is None:
                dangling = True
            elif sha_cell and sha_cell not in EMPTY_SOURCE and rec.get("sha256") and sha_cell != rec["sha256"]:
                dangling = True
        pr = ParsedRow(
            row_id=rid,
            tr_chunk_id=tr_chunk,
            data_row_id=attr if parse_row_id(attr or "") else None,
            cells=cells,
            dangling=dangling,
        )
        result.rows.append(pr)
        if tr_chunk:
            result.row_chunk_map[rid] = tr_chunk
        else:
            result.overreach.append(f"unmapped_chunk:{rid}")
        if dangling:
            result.dangling.append(rid)
    result.data_row_id_survived = had_rows and survived and all(
        parse_row_id(r.data_row_id or "") for r in result.rows if not r.unparseable
    )
    if canonical_ids is not None:
        got = {r.row_id for r in result.rows if r.row_id}
        canon = set(canonical_ids)
        result.html_missing_gaps = sorted(i for i in (canon - got) if "::gap::" in i)
        missing_present = sorted(i for i in (canon - got) if "::present::" in i)
        result.html_missing_gaps = sorted(set(result.html_missing_gaps) | set(missing_present))
        result.invented = sorted(got - canon)
    return result


def row_text_by_id(html: str) -> dict[str, str]:
    parsed = parse(html)
    out: dict[str, str] = {}
    for r in parsed.rows:
        if r.row_id:
            out[r.row_id] = "|".join(r.cells)
    return out
