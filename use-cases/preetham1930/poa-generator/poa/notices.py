"""The export gate. This is hard constraint 1 of the card, and it is structural.

> The document is NOT exportable until read-back confirms both the
> counsel-review notice and the external-notarisation statement are present
> VERBATIM.

The tempting implementation is a check the export path calls. That is one
`if` away from being forgotten, and forgetting it produces exactly the artefact
this build exists to prevent: a power of attorney, in a reviewer's Downloads
folder, with no notice on it and nothing to say the notice ever went missing.

So the check is not a call, it is a **key**. `PoaClient.export` requires a
`NoticeReceipt`. A `NoticeReceipt` cannot be constructed except by
`check_notices()`, which takes a `ChunkMap` from a live read-back and raises if
either notice is missing or altered. There is no default argument, no
`receipt=None` path, and no second constructor. A caller who wants to export
without checking has to change this file, and changing this file is a decision
somebody makes on purpose.

That is the same argument as Decision 13 and Decision 15 in `system/`: the
strong half of a defence is the absence of a path, not a check on the output.

**What "verbatim" means here.** The comparison is against the reader-visible
text (tags removed, entities resolved, runs of whitespace collapsed), because a
document editor is entitled to re-serialise an entity or a line break and that
is punctuation, not content - the measured relaxation Decision 38 already
defines one level up. What it may not do is change, drop or reorder a **word**,
and that is exactly what this preserves. One word paraphrased fails, which is
the case that matters: a rewrite plausibly paraphrases.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from .chunks import ChunkMap, strip_markup
from .errors import NoticeAlteredError, NoticeMissingError
from .library import Library

# The one token that lets a NoticeReceipt be constructed. Module-private and
# never exported: `from .notices import *` cannot reach it, and a caller
# elsewhere in the package that tries to build a receipt by hand gets a
# ValueError naming this file.
_GATE = object()


@dataclass(frozen=True)
class NoticeReceipt:
    """Proof that both notices were read back verbatim, moments ago.

    Only `check_notices()` can make one. It is required by `export()`, so the
    export path cannot be reached without having done the read-back.
    """

    document_id: str
    chunk_count: int
    notices: tuple[str, ...]
    detail: tuple[str, ...] = field(default_factory=tuple)
    _token: object = None

    def __post_init__(self) -> None:
        if self._token is not _GATE:
            raise ValueError(
                "a NoticeReceipt is issued by check_notices() against a live read-back and by "
                "nothing else. Constructing one directly would mean exporting a power of "
                "attorney whose notices nobody looked at - which is the single thing this "
                "module exists to make impossible. See builds/poa-generator/INVARIANTS.md B1."
            )

    def receipt(self) -> str:
        return (
            f"notice gate: {len(self.notices)} required notice(s) found verbatim in "
            f"{self.chunk_count} chunk(s) read back from document {self.document_id}; "
            + "; ".join(self.detail)
        )


def check_notices(chunks: ChunkMap, library: Library, document_id: str = "") -> NoticeReceipt:
    """Raise unless every notice in the library is present, verbatim, in `chunks`.

    Two independent comparisons, on purpose:

    1. the notice text appears in the document's reader-visible text; and
    2. some single chunk's own text **is** the notice, exactly.

    (1) alone would pass a document that had split a notice across two
    paragraphs and inserted a sentence between them. (2) alone would pass a
    document that had kept the notice chunk and appended a second, contradicting
    one - so the caller pairs this with the collateral-damage check, which sees
    any chunk that was added.
    """
    if not library.notices:
        raise NoticeMissingError(
            "config/notices.csv defines no notices, so this gate would pass on any document at "
            "all. An empty guard list is a guard that cannot fail, which is worse than none."
        )

    document_text = chunks.text()
    detail: list[str] = []
    for notice in library.notices.values():
        wanted = _normalise(notice.text)
        if wanted not in _normalise(document_text):
            closest = _closest_chunk(chunks, wanted)
            if closest is None:
                raise NoticeMissingError(
                    f"the {notice.label} ({notice.notice_id}) is not in the document. "
                    f"{len(chunks)} chunk(s) were read back from document "
                    f"{document_id or '(unnamed)'} and none of them carries it, in whole or in "
                    f"part. No export is produced. The notice is:\n  {notice.text}"
                )
            raise NoticeAlteredError(
                f"the {notice.label} ({notice.notice_id}) is present but NOT verbatim. A "
                f"paraphrased notice is a missing notice: the wording is the guarantee.\n"
                f"  expected: {notice.text}\n"
                f"  found   : {closest}\n"
                f"{_diff(wanted, _normalise(closest))}\n"
                f"No export is produced."
            )
        exact = [c for c in chunks.chunks if _normalise(strip_markup(c.html)) == wanted]
        if not exact:
            raise NoticeAlteredError(
                f"the {notice.label} ({notice.notice_id}) appears in the document's text but no "
                f"single chunk holds it on its own. A notice spread across chunks can have a "
                f"sentence inserted into the middle of it and still pass a substring test, so "
                f"this build requires the notice to be one chunk, as it was uploaded. "
                f"No export is produced."
            )
        detail.append(f"{notice.notice_id} verbatim in chunk {exact[0].chunk_id or '(no id)'}")

    return NoticeReceipt(
        document_id=document_id,
        chunk_count=len(chunks),
        notices=tuple(library.notices),
        detail=tuple(detail),
        _token=_GATE,
    )


def _normalise(text: str) -> str:
    return " ".join(strip_markup(text).split())


def _closest_chunk(chunks: ChunkMap, wanted: str) -> str | None:
    """The chunk that looks most like the notice, so the error can show a diff."""
    best, score = None, 0.0
    for chunk in chunks.chunks:
        text = _normalise(strip_markup(chunk.html))
        ratio = difflib.SequenceMatcher(None, wanted, text).ratio()
        if ratio > score:
            best, score = text, ratio
    return best if score >= 0.5 else None


def _diff(expected: str, actual: str) -> str:
    lines = list(
        difflib.unified_diff(
            expected.split(), actual.split(), "expected", "found", lineterm="", n=2
        )
    )
    return "\n".join(f"    {line}" for line in lines[:20])
