"""Reading proposed changes off a chat response.

The task brief is explicit about the trap: "proposed-change content arrives as a
JSON-encoded string and needs a second parse; the final result is already an object.
Missing that second parse is the single most common reason integrators see empty diff
cards where every field reads as undefined."

So the second parse happens here, once, at the boundary — and it is asserted in
tests rather than assumed. Field names are read tolerantly because the exact envelope
is not documented; every shape this module accepts is recorded in test_parsing.py,
and anything it cannot read raises instead of returning an empty list, because an
empty list is indistinguishable from "no violations" and would read as a clean
document.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

CHANGE_LIST_KEYS = ("pending_changes", "proposed_changes", "changes")

# Envelopes the change list has been seen nested inside. `metadata` is where an
# async job carries it while the job sits in `awaiting_approval`.
ENVELOPE_KEYS = ("metadata", "result", "data", "response")

# Present on a *synchronous* chat response: sections the model already rewrote.
# Not a proposal list — there was no approval step — and it carries HTML per chunk
# rather than original/replacement, so reading it as proposals yields empty changes
# that look like a clean document. Detected and reported instead.
APPLIED_KEYS = ("chunk_diffs",)


class UnreadableProposal(Exception):
    """Raised when a response cannot be read. Never silently degraded to 'no findings'."""


@dataclass(frozen=True)
class ProposedChange:
    """One suggested edit.

    The API proposes whole-chunk HTML replacements (`old_html` -> `new_html`), but
    the guard needs a text span to screen. `original` and `replacement` are the
    minimal text-level difference between the two, derived here — see `derive_edit`.
    """

    change_id: str
    chunk_id: str | None
    original: str
    replacement: str
    rule_id: str | None = None
    note: str | None = None
    old_html: str | None = None
    new_html: str | None = None
    operation: str = "edit"

    @property
    def is_noop(self) -> bool:
        return self.original == self.replacement


def second_parse(value: Any) -> Any:
    """Decode a JSON-encoded string once. Objects pass through untouched.

    Tolerates double encoding, which is what actually bites integrators.
    """
    seen = 0
    while isinstance(value, str) and seen < 2:
        stripped = value.strip()
        if not stripped or stripped[0] not in "[{\"":
            return value
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            return value
        seen += 1
    return value


def derive_edit(old_html: str, new_html: str) -> tuple[str, str]:
    """The minimal text-level change between two versions of one chunk.

    Captured live on 2026-08-19: a pending change carries the whole chunk's HTML
    before and after, not the words that changed. Screening a whole paragraph would
    be useless — it always contains itself once — so the actual edit is recovered by
    diffing the visible text and returning the smallest span that differs.
    """
    from .guard import Document

    before, after = Document(old_html).text, Document(new_html).text
    if before == after:
        return before, after

    head = 0
    while head < len(before) and head < len(after) and before[head] == after[head]:
        head += 1
    tail = 0
    while (tail < len(before) - head and tail < len(after) - head
           and before[-1 - tail] == after[-1 - tail]):
        tail += 1

    # Widen to whole words so the span is something a reader would recognise.
    while head > 0 and not before[head - 1].isspace():
        head -= 1
    end_before, end_after = len(before) - tail, len(after) - tail
    while end_before < len(before) and not before[end_before].isspace():
        end_before += 1
        end_after += 1
    return before[head:end_before], after[head:end_after]


def _field(d: dict, *names: str, default: Any = None) -> Any:
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return default


def parse_proposed_changes(payload: Any) -> list[ProposedChange]:
    """Pull the change list out of a chat response, whatever envelope it arrives in."""
    payload = second_parse(payload)
    if not isinstance(payload, dict):
        raise UnreadableProposal(f"expected an object, got {type(payload).__name__}")

    raw = None
    explicit_empty = False
    for key in CHANGE_LIST_KEYS:
        if key in payload:
            raw = second_parse(payload[key])
            # An explicit null means "nothing pending", which is a real answer.
            explicit_empty = raw is None
            break
    if raw is None:
        for key in ENVELOPE_KEYS:
            inner = second_parse(payload.get(key))
            if isinstance(inner, dict):
                for k in CHANGE_LIST_KEYS:
                    if k in inner:
                        raw = second_parse(inner[k])
                        # A null nested in an envelope means the same as a null at
                        # the top level: nothing pending. This is the shape that
                        # matters, since the list lives in `metadata` by design.
                        explicit_empty = explicit_empty or raw is None
                        break
            if raw is not None:
                break

    if raw is None:
        if explicit_empty:
            return []
        applied = [k for k in APPLIED_KEYS if payload.get(k)]
        if applied:
            raise UnreadableProposal(
                f"response carries {applied[0]} but no proposal list: this looks like "
                f"a synchronous chat that applied its edits without an approval step. "
                f"Use chat_async with approval_mode='ask_every_time'."
            )
        raise UnreadableProposal(
            f"no change list found; keys were {sorted(payload)[:12]}"
        )
    if not isinstance(raw, list):
        raise UnreadableProposal(f"change list is {type(raw).__name__}, not a list")

    out = []
    for i, item in enumerate(raw):
        item = second_parse(item)
        if not isinstance(item, dict):
            raise UnreadableProposal(f"change {i} is {type(item).__name__}, not an object")
        content = second_parse(_field(item, "content", "diff", default={}))
        if not isinstance(content, dict):
            content = {}

        old_html = _field(item, "old_html", "before_html")
        new_html = _field(item, "new_html", "after_html")

        original = _field(item, "original", "old_text", "before",
                          default=_field(content, "original", "old", default=""))
        replacement = _field(item, "replacement", "new_text", "after", "proposed",
                             default=_field(content, "replacement", "new", default=""))

        # The live shape: whole-chunk HTML rather than a text span. Recover the span.
        if old_html and new_html and not str(original).strip():
            original, replacement = derive_edit(old_html, new_html)

        out.append(
            ProposedChange(
                change_id=str(_field(item, "change_id", "id", default=f"change-{i}")),
                chunk_id=_field(item, "chunk_id", "chunkId"),
                original=original,
                replacement=replacement,
                rule_id=_field(item, "rule_id", "rule"),
                note=_field(item, "note", "reason", "explanation", "ai_explanation"),
                old_html=old_html,
                new_html=new_html,
                operation=str(_field(item, "operation", default="edit")),
            )
        )
    return out
