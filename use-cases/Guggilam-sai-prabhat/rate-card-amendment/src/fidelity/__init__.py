"""Fidelity and surgical-change verification layer.

Proves, with measurable evidence rather than assertion, that a SuperDocs
export changed only what an approved proposal authorized:

  - `document_model.py`  — parses a text document (markdown/html/txt — the
    only formats SuperDocs export actually produces, see
    `src/integrations/superdocs_client.py::export_document`) into
    comparable structural units: sections/headings, paragraphs, tables,
    and non-target text. Headers/footers/footnotes are real DOCX package
    concepts this app's export path never produces; the model reports
    them `not_applicable` rather than silently claiming they were checked.
  - `intended_edits.py`  — derives the intended-edit set from an
    `AmendmentCase`'s pending changes and per-change approve/reject
    decisions (`src/amendment_case.py`) — the only authoritative source
    of "what was supposed to change".
  - `compare.py`          — diffs original vs exported structural models,
    classifies every difference as intended or unintended, and computes
    the honest identity verdict (byte/structural/semantic/not_verified).
  - `report.py`           — renders the comparison as a machine-readable
    JSON fidelity report and a human-readable Markdown/HTML report.

See `docs/FIDELITY_METHOD.md` for the full methodology and the meaning of
each verdict tier.
"""

from src.fidelity.case_fidelity import (
    build_excluded_contract_report,
    build_fidelity_report,
    write_case_fidelity_artifacts,
)
from src.fidelity.compare import FidelityReport, compare_documents
from src.fidelity.document_model import DocumentModel, parse_document
from src.fidelity.intended_edits import IntendedEdit, derive_intended_edits

__all__ = [
    "DocumentModel",
    "parse_document",
    "IntendedEdit",
    "derive_intended_edits",
    "FidelityReport",
    "compare_documents",
    "build_fidelity_report",
    "build_excluded_contract_report",
    "write_case_fidelity_artifacts",
]
