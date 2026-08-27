"""
Realistic edit-task generation.

For each document, produces a small multi-turn "editing session": a sequence
of targeted-edit instructions a real user might issue, varied across edit
*types* so the benchmark doesn't collapse to a single number (per the card's
"what strong looks like": document sizes and edit types varied enough that
the curve, not one number, is the finding).

Edit types modeled:
  - reword       : rewrite a section's tone/phrasing, meaning preserved
  - factual_fix  : change one fact (a date, a number, a party name) in a section
  - shrink       : compress a section to ~half its length
  - expand       : add a clarifying paragraph to a section
  - insert       : add a brand-new short section after an existing one

Each EditTask names an explicit target_section_id, which is what makes the
"section-level editing" arm well-defined; the "whole-document regeneration"
arm ignores the target and resends/regenerates the entire document instead.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List

from benchmark.corpus import Document

EDIT_TYPES = ["reword", "factual_fix", "shrink", "expand", "insert"]


@dataclass
class EditTask:
    task_id: str
    doc_id: str
    turn: int
    edit_type: str
    target_section_id: str
    instruction: str


_INSTRUCTION_TEMPLATES = {
    "reword": "Rewrite section {sid} ('{heading}') in a more formal register. Keep the meaning identical.",
    "factual_fix": "In section {sid} ('{heading}'), change the payment/notice period mentioned to 45 days.",
    "shrink": "Compress section {sid} ('{heading}') to roughly half its current length without losing the key obligation.",
    "expand": "Expand section {sid} ('{heading}') with one clarifying paragraph about exceptions to the rule described.",
    "insert": "Insert a new short section immediately after {sid} ('{heading}') covering escalation contacts.",
}


def generate_edit_session(doc: Document, num_turns: int, seed: int) -> List[EditTask]:
    """Generates a deterministic multi-turn edit session for one document.

    Turns cycle through edit types and target increasingly-arbitrary sections,
    simulating a real back-and-forth review session rather than one isolated edit.
    """
    rng = random.Random(seed)
    tasks: List[EditTask] = []
    if not doc.sections:
        return tasks

    for turn in range(num_turns):
        edit_type = EDIT_TYPES[turn % len(EDIT_TYPES)]
        section = rng.choice(doc.sections)
        instruction = _INSTRUCTION_TEMPLATES[edit_type].format(
            sid=section.id, heading=section.heading
        )
        tasks.append(
            EditTask(
                task_id=f"{doc.doc_id}-t{turn:02d}",
                doc_id=doc.doc_id,
                turn=turn,
                edit_type=edit_type,
                target_section_id=section.id,
                instruction=instruction,
            )
        )
    return tasks


def generate_all_sessions(docs, turns_per_doc: int = 5, seed: int = 7):
    """Returns {doc_id: [EditTask, ...]} for every document in docs."""
    sessions = {}
    for i, doc in enumerate(docs):
        sessions[doc.doc_id] = generate_edit_session(doc, turns_per_doc, seed=seed + i)
    return sessions
