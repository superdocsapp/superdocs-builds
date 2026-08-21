"""Compare two canonical Documents and report exactly what differs.

Two rules govern this module.

1. The edit target is exempt from content comparison and nothing else is. A
   round-trip that changes a cell nobody asked it to change is a finding even
   if the document still looks fine.

2. A finding is never asserted where it cannot be observed. If a stage did not
   run, the case is UNVERIFIABLE, not a failure. "Broken" and "not measured"
   are different words here and the report keeps them apart.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

from .model import Cell, Document, Table

STRUCTURAL = "structural"
CONTENT = "content"
FORMATTING = "formatting"

# Verdicts
PASS = "PASS"
FAIL = "FAIL"
UNVERIFIABLE = "UNVERIFIABLE"
ERROR = "ERROR"


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    where: str
    expected: str
    actual: str

    def key(self) -> tuple:
        return (self.severity, self.code, self.where)

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        return f"[{self.severity}/{self.code}] {self.where}: expected {self.expected!r}, got {self.actual!r}"


def _norm(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _norm_text(s: str) -> str:
    """Whitespace-insensitive but character-exact otherwise.

    Deliberately does NOT normalise unicode: an em dash turning into a hyphen,
    or a non-breaking space into a space, is a finding, not noise.
    """
    return " ".join(s.split())


def _cmp_cell(a: Cell, b: Cell, where: str, exempt: bool,
              out: list[Finding]) -> None:
    if a.row_span != b.row_span:
        out.append(Finding(STRUCTURAL, "row_span", where,
                           str(a.row_span), str(b.row_span)))
    if a.col_span != b.col_span:
        out.append(Finding(STRUCTURAL, "col_span", where,
                           str(a.col_span), str(b.col_span)))

    if not exempt:
        at, bt = _norm_text(a.text), _norm_text(b.text)
        if at != bt:
            out.append(Finding(CONTENT, "cell_text", where, at, bt))
        if len(a.paragraphs) != len(b.paragraphs):
            out.append(Finding(CONTENT, "paragraph_count", where,
                               str(len(a.paragraphs)), str(len(b.paragraphs))))

    for attr, code in (
        ("alignment", "alignment"),
        ("shading", "shading"),
        ("valign", "valign"),
        ("text_direction", "text_direction"),
    ):
        av, bv = _norm(getattr(a, attr)), _norm(getattr(b, attr))
        if av != bv:
            out.append(Finding(FORMATTING, code, where, av, bv))

    if a.width_dxa is not None and b.width_dxa is not None:
        if a.width_dxa != b.width_dxa:
            out.append(Finding(FORMATTING, "cell_width", where,
                               str(a.width_dxa), str(b.width_dxa)))

    if len(a.nested) != len(b.nested):
        out.append(Finding(STRUCTURAL, "nested_table_count", where,
                           str(len(a.nested)), str(len(b.nested))))
    else:
        for i, (na, nb) in enumerate(zip(a.nested, b.nested)):
            _cmp_table(na, nb, f"{where}>nested[{i}]", exempt, out)  # noqa


def _cmp_table(a: Table, b: Table, where: str, exempt_all: bool,
               out: list[Finding],
               targets: list[tuple[int, int]] | None = None) -> None:
    if a.n_rows != b.n_rows:
        out.append(Finding(STRUCTURAL, "row_count", where,
                           str(a.n_rows), str(b.n_rows)))
    if a.n_cols != b.n_cols:
        out.append(Finding(STRUCTURAL, "col_count", where,
                           str(a.n_cols), str(b.n_cols)))

    occ_a, occ_b = a.occupancy(), b.occupancy()
    if occ_a != occ_b:
        diff = sorted(set(occ_a) ^ set(occ_b))[:4]
        mism = [k for k in sorted(set(occ_a) & set(occ_b)) if occ_a[k] != occ_b[k]][:4]
        out.append(Finding(
            STRUCTURAL, "grid_topology", where,
            f"{len(occ_a)} covered cells",
            f"{len(occ_b)} covered cells; missing/extra={diff}; remapped={mism}",
        ))

    if a.header_rows != b.header_rows:
        out.append(Finding(FORMATTING, "header_rows", where,
                           str(a.header_rows), str(b.header_rows)))
    if a.col_widths and b.col_widths and a.col_widths != b.col_widths:
        out.append(Finding(FORMATTING, "col_widths", where,
                           str(a.col_widths), str(b.col_widths)))
    if _norm(a.layout) != _norm(b.layout):
        out.append(Finding(FORMATTING, "table_layout", where,
                           _norm(a.layout), _norm(b.layout)))

    ea, eb = a.border_edges(), b.border_edges()
    for key in sorted(set(ea) | set(eb)):
        av, bv = _norm(ea.get(key)), _norm(eb.get(key))
        if av != bv:
            kind = "row rule above" if key[0] == "h" else "column rule left of"
            out.append(Finding(FORMATTING, "border_edge",
                               f"{where} {kind} ({key[1]}, {key[2]})", av, bv))

    anchors_a, anchors_b = a.anchors(), b.anchors()
    for pos in sorted(set(anchors_a) | set(anchors_b)):
        ca, cb = anchors_a.get(pos), anchors_b.get(pos)
        cw = f"{where} cell{pos}"
        if ca is None:
            out.append(Finding(STRUCTURAL, "unexpected_cell", cw, "-",
                               _norm_text(cb.text)[:60]))
            continue
        if cb is None:
            out.append(Finding(STRUCTURAL, "missing_cell", cw,
                               _norm_text(ca.text)[:60], "-"))
            continue
        exempt = exempt_all
        for t in (targets or []):
            anchor = a.cell_at(*t)
            if anchor is not None and (anchor.row, anchor.col) == pos:
                exempt = True
                break
        _cmp_cell(ca, cb, cw, exempt, out)


# Attributes that plain HTML has no standard slot for. When the stage under
# comparison is the HTML intermediate, their absence is unmeasurable, not
# proven lost -- so they are withheld from findings and reported separately.
HTML_UNREPRESENTABLE = frozenset({
    "col_widths", "cell_width", "table_layout",
    "text_direction", "border_edge",
})
# header_rows was in this set until the API's response turned out to carry a
# real <thead>. It is representable, so withholding it hid the useful fact:
# the header marking survives ingest and is lost on export.


def compare(before: Document, after: Document,
            target=None, profile: str = "docx") -> list[Finding]:
    """target is (table_index, row, col), or a list of them, exempt from
    content checks. Every cell not named is an invariant.

    profile='html' withholds findings for attributes HTML cannot express.
    """
    out: list[Finding] = []
    if target is None:
        targets: list[tuple[int, int, int]] = []
    elif isinstance(target, tuple) and target and isinstance(target[0], int):
        targets = [target]
    else:
        targets = list(target)

    if len(before.tables) != len(after.tables):
        out.append(Finding(STRUCTURAL, "table_count", "document",
                           str(len(before.tables)), str(len(after.tables))))

    for i, (ta, tb) in enumerate(zip(before.tables, after.tables)):
        tgts = [(t[1], t[2]) for t in targets if t[0] == i]
        _cmp_table(ta, tb, f"table[{i}]", False, out, tgts)

    a_paras = [_norm_text(p) for p in before.body_paragraphs]
    b_paras = [_norm_text(p) for p in after.body_paragraphs]
    if a_paras != b_paras:
        missing = [p for p in a_paras if p not in b_paras][:3]
        out.append(Finding(CONTENT, "body_paragraphs", "document",
                           f"{len(a_paras)} paragraphs",
                           f"{len(b_paras)} paragraphs; missing={missing}"))

    if profile == "html":
        out = [f for f in out if f.code not in HTML_UNREPRESENTABLE]
    return out


def unmeasurable_at_html_stage(findings: list[Finding]) -> list[str]:
    """Codes withheld under the html profile, for honest reporting."""
    return sorted({f.code for f in findings if f.code in HTML_UNREPRESENTABLE})


def attribute(edit_findings: list[Finding],
              control_findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """Split edit-run findings into (caused_by_edit, caused_by_round_trip).

    A finding that also occurs on a no-op control run is a property of ingest
    and export, not of the edit. Separating these is the difference between
    'the editor broke my table' and 'the file format round-trip did'.
    """
    control_keys = {f.key() for f in control_findings}
    by_edit = [f for f in edit_findings if f.key() not in control_keys]
    by_round_trip = [f for f in edit_findings if f.key() in control_keys]
    return by_edit, by_round_trip


def verdict(edit_applied: bool | None, findings: list[Finding]) -> str:
    if edit_applied is None:
        return UNVERIFIABLE
    if not edit_applied:
        return FAIL
    return PASS if not findings else FAIL


def summarise(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
        counts[f"{f.severity}:{f.code}"] = counts.get(f"{f.severity}:{f.code}", 0) + 1
    return counts
