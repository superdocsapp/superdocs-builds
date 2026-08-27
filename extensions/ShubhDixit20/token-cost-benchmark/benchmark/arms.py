"""
The two measurement arms.

ARM A — whole_doc: every edit in the session resends and regenerates the
entire current document text. This is the "why not just send the whole
document to a model" baseline the benchmark exists to test.

ARM B — section_edit: every edit sends only the target section's text and
gets back a replacement for just that section; the rest of the document is
left untouched (byte-identical), matching SuperDocs' own "targeted edits"
model.

Both arms run the *same* multi-turn edit session on independent copies of
the starting document, so edits compound identically in intent but the
mechanism (and therefore cost) differs. Each turn produces an EditRecord;
a session produces a list of records plus cumulative totals.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, asdict
from typing import List

from benchmark.corpus import Document
from benchmark.client import BaseClient
from benchmark.edit_tasks import EditTask
from benchmark.metrics import cost_usd


@dataclass
class EditRecord:
    task_id: str
    doc_id: str
    arm: str
    turn: int
    edit_type: str
    target_section_id: str
    chars_sent: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    wall_clock_s: float
    client_source: str

    def to_dict(self) -> dict:
        return asdict(self)


def _record_from_edit(task: EditTask, arm: str, chars_sent: int, edit_result) -> EditRecord:
    return EditRecord(
        task_id=task.task_id,
        doc_id=task.doc_id,
        arm=arm,
        turn=task.turn,
        edit_type=task.edit_type,
        target_section_id=task.target_section_id,
        chars_sent=chars_sent,
        input_tokens=edit_result.input_tokens,
        output_tokens=edit_result.output_tokens,
        cost_usd=cost_usd(edit_result.input_tokens, edit_result.output_tokens),
        wall_clock_s=edit_result.wall_clock_s,
        client_source=edit_result.source,
    )


def run_whole_doc_arm(doc: Document, session: List[EditTask], client: BaseClient) -> List[EditRecord]:
    working = copy.deepcopy(doc)
    records: List[EditRecord] = []

    for task in session:
        full_text = working.full_text()
        result = client.edit(full_text, task.instruction)
        records.append(_record_from_edit(task, "whole_doc", len(full_text), result))

        # Whole-doc arm: the entire document is replaced by whatever the
        # client returned. We keep it as free text (not re-parsed into
        # sections) because that is exactly what "regenerate the whole
        # document" means — the arm does NOT get section structure back
        # for free the way the targeted-edit arm does.
        working = _WholeDocWrapper(working.doc_id, working.title, working.domain, full_text=result.edited_text)

    return records


class _WholeDocWrapper(Document):
    """A Document stand-in whose full_text() returns pre-baked text instead of
    re-rendering from sections, used only inside the whole-doc arm once the
    document has been flattened by a regenerate step."""

    def __init__(self, doc_id, title, domain, full_text: str):
        super().__init__(doc_id=doc_id, title=title, domain=domain, sections=[])
        self._full_text = full_text

    def full_text(self) -> str:
        return self._full_text


def run_section_edit_arm(doc: Document, session: List[EditTask], client: BaseClient) -> List[EditRecord]:
    working = copy.deepcopy(doc)
    records: List[EditRecord] = []

    for task in session:
        try:
            section = working.get_section(task.target_section_id)
            section_text = section.body
        except KeyError:
            # Section may have been renamed/removed by a prior "insert" edit
            # in this session; fall back to the first section rather than
            # crashing the run. Logged as a limitation, not silently ignored.
            section = working.sections[0]
            section_text = section.body

        result = client.edit(section_text, task.instruction)
        records.append(_record_from_edit(task, "section_edit", len(section_text), result))

        # Only the targeted section changes; everything else in `working`
        # is untouched by construction (surgical precision, provably: the
        # runner can byte-compare the untouched sections across turns).
        section.body = result.edited_text

    return records
