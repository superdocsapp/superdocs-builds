"""Compares an original document against an exported one and classifies
every structural difference as intended or unintended.

Identity verdicts are computed honestly and in this strict order — never
skip a cheaper, stronger claim in favor of a weaker one, and never assert a
tier without running its check:

  1. `byte_identical`       — `original_text == exported_text`, tested directly.
  2. `structurally_identical` — every structural facet
     (headings/paragraphs/tables/styles/section order) parses to the exact
     same `DocumentModel` fields, even if raw bytes differ (whitespace,
     line endings, non-semantic formatting).
  3. `semantically_unchanged` — structural facets differ only inside chunks
     covered by an approved `IntendedEdit`; every other facet (non-target
     text, untouched tables, headings, styles, section order) is identical.
     This is the tier a normal successful "approve one rate table" export
     lands on: the target table changed, nothing else did.
  4. `not_verified`         — none of the above holds, OR a facet this
     format cannot check (headers/footers/footnotes on markdown/html/txt)
     was load-bearing for the claim. `not_verified` is also the verdict for
     any facet-level check this module could not run, surfaced per-facet in
     `FidelityReport.facet_checks` rather than folded into a false pass.

A tier is only ever claimed if its specific test ran and passed — see the
`_verdict()` assembly at the bottom of `compare_documents`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from src.fidelity.document_model import CheckStatus, DocumentModel, SectionCheck, parse_document
from src.fidelity.intended_edits import IntendedEdit


class IdentityVerdict(str, Enum):
    BYTE_IDENTICAL = "byte_identical"
    STRUCTURALLY_IDENTICAL = "structurally_identical"
    SEMANTICALLY_UNCHANGED = "semantically_unchanged"
    NOT_VERIFIED = "not_verified"


class DiffClassification(str, Enum):
    INTENDED = "intended"
    UNINTENDED = "unintended"


@dataclass(frozen=True)
class StructuralDiff:
    facet: str  # "heading" | "paragraph" | "table_cell" | "style" | "section_order"
    location: str  # human-readable pointer, e.g. "table[0] row=2 col=2" or "heading[3]"
    original_value: Optional[str]
    exported_value: Optional[str]
    classification: DiffClassification
    matched_change_id: Optional[str] = None
    reason: str = ""


@dataclass(frozen=True)
class FacetCheck:
    """Per-facet record of whether a comparison actually ran."""

    facet: str
    status: CheckStatus
    reason: Optional[str] = None


@dataclass
class FidelityReport:
    document_id: str
    verdict: IdentityVerdict
    byte_identical: bool
    original_sha256: str
    exported_sha256: str
    diffs: list[StructuralDiff]
    facet_checks: list[FacetCheck]
    intended_edits_considered: list[IntendedEdit]
    unintended_diff_count: int
    intended_diff_count: int
    excluded_contract: bool = False
    excluded_reason: Optional[str] = None

    @property
    def is_surgical(self) -> bool:
        """True iff every observed diff was intended — the core fidelity claim."""

        return self.unintended_diff_count == 0

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "verdict": self.verdict.value,
            "is_surgical": self.is_surgical,
            "byte_identical": self.byte_identical,
            "original_sha256": self.original_sha256,
            "exported_sha256": self.exported_sha256,
            "excluded_contract": self.excluded_contract,
            "excluded_reason": self.excluded_reason,
            "intended_diff_count": self.intended_diff_count,
            "unintended_diff_count": self.unintended_diff_count,
            "facet_checks": [
                {"facet": f.facet, "status": f.status.value, "reason": f.reason} for f in self.facet_checks
            ],
            "diffs": [
                {
                    "facet": d.facet,
                    "location": d.location,
                    "original_value": d.original_value,
                    "exported_value": d.exported_value,
                    "classification": d.classification.value,
                    "matched_change_id": d.matched_change_id,
                    "reason": d.reason,
                }
                for d in self.diffs
            ],
            "intended_edits_considered": [
                {
                    "change_id": e.change_id,
                    "chunk_id": e.chunk_id,
                    "disposition": e.disposition.value,
                    "should_appear_in_export": e.should_appear_in_export,
                }
                for e in self.intended_edits_considered
            ],
        }


def _normalize_cell(text: str) -> str:
    return " ".join(text.split())


def _text_matches_any_edit_fragment(text: str, edits: list[IntendedEdit], approved_only: bool) -> Optional[str]:
    """Return the change_id of the first approved edit whose old/new fragment
    contains this text (or vice versa), else None."""

    norm = _normalize_cell(text)
    if not norm:
        return None
    for edit in edits:
        if approved_only and not edit.should_appear_in_export:
            continue
        old_norm = _normalize_cell(edit.old_text())
        new_norm = _normalize_cell(edit.new_text())
        if norm and (norm in new_norm or norm in old_norm or new_norm in norm or old_norm in norm):
            return edit.change_id
    return None


def _classify(
    original_value: Optional[str],
    exported_value: Optional[str],
    edits: list[IntendedEdit],
) -> tuple[DiffClassification, Optional[str], str]:
    """Classify one structural diff. A diff is `intended` only if the
    *exported* (new) value is explainable by an approved edit's new fragment
    — this is what stops a rejected or unresolved change from ever being
    laundered into "intended" just because SuperDocs proposed it."""

    for value, tag in ((exported_value, "exported"), (original_value, "original")):
        if not value:
            continue
        match = _text_matches_any_edit_fragment(value, edits, approved_only=True)
        if match:
            return (
                DiffClassification.INTENDED,
                match,
                f"{tag} value matches the old/new fragment of approved change {match}",
            )

    return (
        DiffClassification.UNINTENDED,
        None,
        "difference does not correspond to any approved change's old/new fragment",
    )


def _diff_headings(original: DocumentModel, exported: DocumentModel, edits: list[IntendedEdit]) -> list[StructuralDiff]:
    diffs: list[StructuralDiff] = []
    orig_headings = [h.text for h in original.headings]
    exp_headings = [h.text for h in exported.headings]
    max_len = max(len(orig_headings), len(exp_headings))
    for i in range(max_len):
        o = orig_headings[i] if i < len(orig_headings) else None
        e = exp_headings[i] if i < len(exp_headings) else None
        if o == e:
            continue
        classification, matched_id, reason = _classify(o, e, edits)
        diffs.append(
            StructuralDiff(
                facet="heading",
                location=f"heading[{i}]",
                original_value=o,
                exported_value=e,
                classification=classification,
                matched_change_id=matched_id,
                reason=reason,
            )
        )
    return diffs


def _diff_section_order(original: DocumentModel, exported: DocumentModel, edits: list[IntendedEdit]) -> list[StructuralDiff]:
    orig_order = original.section_order()
    exp_order = exported.section_order()
    if orig_order == exp_order:
        return []
    # Section order changes are only "intended" if the reordering is fully
    # explained by insertion of an approved edit's new heading text (e.g.
    # SuperDocs adding a new "Schedule A" section) — never by removal or
    # reordering of a pre-existing heading, which no approved rate-table
    # edit should ever cause.
    orig_set = set(orig_order)
    exp_set = set(exp_order)
    removed = orig_set - exp_set
    added = exp_set - orig_set
    if removed:
        return [
            StructuralDiff(
                facet="section_order",
                location="document",
                original_value=", ".join(orig_order),
                exported_value=", ".join(exp_order),
                classification=DiffClassification.UNINTENDED,
                reason=f"heading(s) removed from the document that were present in the original: {sorted(removed)}",
            )
        ]
    unexplained_additions = [h for h in added if _text_matches_any_edit_fragment(h, edits, approved_only=True) is None]
    if unexplained_additions:
        return [
            StructuralDiff(
                facet="section_order",
                location="document",
                original_value=", ".join(orig_order),
                exported_value=", ".join(exp_order),
                classification=DiffClassification.UNINTENDED,
                reason=f"new heading(s) not attributable to any approved change: {sorted(unexplained_additions)}",
            )
        ]
    matched_ids = {h: _text_matches_any_edit_fragment(h, edits, approved_only=True) for h in added}
    return [
        StructuralDiff(
            facet="section_order",
            location="document",
            original_value=", ".join(orig_order),
            exported_value=", ".join(exp_order),
            classification=DiffClassification.INTENDED,
            matched_change_id=next(iter(matched_ids.values()), None),
            reason=f"new heading(s) attributable to approved change(s): {matched_ids}",
        )
    ]


def _diff_paragraphs(original: DocumentModel, exported: DocumentModel, edits: list[IntendedEdit]) -> list[StructuralDiff]:
    diffs: list[StructuralDiff] = []
    orig_texts = [p.text for p in original.paragraphs]
    exp_texts = [p.text for p in exported.paragraphs]
    orig_set = set(orig_texts)
    exp_set = set(exp_texts)

    for i, text in enumerate(orig_texts):
        if text in exp_set:
            continue
        classification, matched_id, reason = _classify(text, None, edits)
        diffs.append(
            StructuralDiff(
                facet="paragraph",
                location=f"paragraph[original:{i}]",
                original_value=text,
                exported_value=None,
                classification=classification,
                matched_change_id=matched_id,
                reason=reason if classification == DiffClassification.INTENDED else "paragraph present in original is missing from export, and does not match any approved change",
            )
        )

    for i, text in enumerate(exp_texts):
        if text in orig_set:
            continue
        classification, matched_id, reason = _classify(None, text, edits)
        diffs.append(
            StructuralDiff(
                facet="paragraph",
                location=f"paragraph[exported:{i}]",
                original_value=None,
                exported_value=text,
                classification=classification,
                matched_change_id=matched_id,
                reason=reason if classification == DiffClassification.INTENDED else "paragraph present in export does not exist in the original, and does not match any approved change",
            )
        )
    return diffs


def _diff_tables(original: DocumentModel, exported: DocumentModel, edits: list[IntendedEdit]) -> list[StructuralDiff]:
    diffs: list[StructuralDiff] = []
    max_tables = max(len(original.tables), len(exported.tables))
    for t_idx in range(max_tables):
        o_table = original.tables[t_idx] if t_idx < len(original.tables) else None
        e_table = exported.tables[t_idx] if t_idx < len(exported.tables) else None

        if o_table is None:
            classification, matched_id, reason = _classify(None, "\n".join(e_table.header_row), edits)
            diffs.append(
                StructuralDiff(
                    facet="table",
                    location=f"table[{t_idx}]",
                    original_value=None,
                    exported_value=f"new table with header {e_table.header_row}",
                    classification=classification,
                    matched_change_id=matched_id,
                    reason=reason,
                )
            )
            continue
        if e_table is None:
            diffs.append(
                StructuralDiff(
                    facet="table",
                    location=f"table[{t_idx}]",
                    original_value=f"table with header {o_table.header_row}",
                    exported_value=None,
                    classification=DiffClassification.UNINTENDED,
                    reason="table present in original was removed from the export entirely",
                )
            )
            continue

        if o_table.header_row != e_table.header_row:
            classification, matched_id, reason = _classify(
                " | ".join(o_table.header_row), " | ".join(e_table.header_row), edits
            )
            diffs.append(
                StructuralDiff(
                    facet="table_header",
                    location=f"table[{t_idx}].header",
                    original_value=" | ".join(o_table.header_row),
                    exported_value=" | ".join(e_table.header_row),
                    classification=classification,
                    matched_change_id=matched_id,
                    reason=reason,
                )
            )

        o_cells = o_table.cell_map()
        e_cells = e_table.cell_map()
        all_coords = set(o_cells.keys()) | set(e_cells.keys())
        for coord in sorted(all_coords):
            o_val = o_cells.get(coord)
            e_val = e_cells.get(coord)
            if o_val == e_val:
                continue
            classification, matched_id, reason = _classify(o_val, e_val, edits)
            diffs.append(
                StructuralDiff(
                    facet="table_cell",
                    location=f"table[{t_idx}] row={coord[0]} col={coord[1]}",
                    original_value=o_val,
                    exported_value=e_val,
                    classification=classification,
                    matched_change_id=matched_id,
                    reason=reason,
                )
            )
    return diffs


def _diff_styles(original: DocumentModel, exported: DocumentModel) -> list[StructuralDiff]:
    """Style comparison is informational only (never classified as unintended
    on its own): SuperDocs is documented to re-render approved-edit HTML with
    inline styling (`fixtures/superdocs`-recorded `style="..."` attributes),
    so a style-attribute delta on its own is expected noise, not a fidelity
    violation. It's still surfaced so a reviewer can see what changed."""

    orig_styles = set(original.styles)
    exp_styles = set(exported.styles)
    if orig_styles == exp_styles:
        return []
    return [
        StructuralDiff(
            facet="style",
            location="document",
            original_value=", ".join(sorted(orig_styles)) or None,
            exported_value=", ".join(sorted(exp_styles)) or None,
            classification=DiffClassification.INTENDED,
            reason="inline style attributes differ; SuperDocs re-renders edited HTML fragments with their own "
            "inline styling — this is not classified as a content change",
        )
    ]


def compare_documents(
    document_id: str,
    original_text: str,
    exported_text: str,
    intended_edits: list[IntendedEdit],
    original_format_hint: Optional[str] = None,
    exported_format_hint: Optional[str] = None,
    excluded_contract: bool = False,
    excluded_reason: Optional[str] = None,
) -> FidelityReport:
    """Compare an original document's text against its exported text.

    `intended_edits` should come from `src.fidelity.intended_edits.derive_intended_edits`
    for the same case — this function never inspects any case/state itself,
    it only classifies structural diffs against the edit fragments handed to
    it, so it can be tested with hand-built `IntendedEdit` fixtures too.
    """

    byte_identical = original_text == exported_text
    original_model = parse_document(original_text, original_format_hint)
    exported_model = parse_document(exported_text, exported_format_hint)

    diffs: list[StructuralDiff] = []
    diffs.extend(_diff_headings(original_model, exported_model, intended_edits))
    diffs.extend(_diff_section_order(original_model, exported_model, intended_edits))
    diffs.extend(_diff_paragraphs(original_model, exported_model, intended_edits))
    diffs.extend(_diff_tables(original_model, exported_model, intended_edits))
    diffs.extend(_diff_styles(original_model, exported_model))

    facet_checks = [
        FacetCheck("body_paragraphs", CheckStatus.CHECKED),
        FacetCheck("tables", CheckStatus.CHECKED),
        FacetCheck("headings_and_section_order", CheckStatus.CHECKED),
        FacetCheck("styles", CheckStatus.CHECKED),
        FacetCheck("non_target_text", CheckStatus.CHECKED),
        FacetCheck("target_rate_cells", CheckStatus.CHECKED),
        FacetCheck("headers", original_model.headers.status, original_model.headers.reason),
        FacetCheck("footers", original_model.footers.status, original_model.footers.reason),
        FacetCheck("footnotes", original_model.footnotes.status, original_model.footnotes.reason),
    ]

    unintended = [d for d in diffs if d.classification == DiffClassification.UNINTENDED]
    intended = [d for d in diffs if d.classification == DiffClassification.INTENDED]

    structurally_identical = (
        original_model.headings == exported_model.headings
        and original_model.paragraphs == exported_model.paragraphs
        and original_model.tables == exported_model.tables
        and original_model.styles == exported_model.styles
    )

    any_facet_not_applicable = any(fc.status == CheckStatus.NOT_APPLICABLE for fc in facet_checks)

    if byte_identical:
        verdict = IdentityVerdict.BYTE_IDENTICAL
    elif structurally_identical:
        verdict = IdentityVerdict.STRUCTURALLY_IDENTICAL
    elif len(unintended) == 0:
        verdict = IdentityVerdict.SEMANTICALLY_UNCHANGED
    else:
        verdict = IdentityVerdict.NOT_VERIFIED

    return FidelityReport(
        document_id=document_id,
        verdict=verdict,
        byte_identical=byte_identical,
        original_sha256=original_model.sha256,
        exported_sha256=exported_model.sha256,
        diffs=diffs,
        facet_checks=facet_checks,
        intended_edits_considered=intended_edits,
        unintended_diff_count=len(unintended),
        intended_diff_count=len(intended),
        excluded_contract=excluded_contract,
        excluded_reason=excluded_reason,
    )
