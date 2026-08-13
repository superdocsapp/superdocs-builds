"""Checking the published documents against what this program says it published.

Everything else in this project checks the documents *before* they are uploaded.
This checks them after, by reading them back off the service -- which is a
different claim, and the only one that survives the question "yes, but is that
what is actually there?"

Two things are checked, and they are the two grading criteria that can go wrong
silently.

**Every figure points at the drawing that was uploaded for it.** Compared by URL
*path*, because the service appends a ~750-character signed query when it serves
an image and that query differs on every read. The path is the identity of the
file; the query is the service's signature on it.

**The manual and the card still agree.** Word for word, on the served documents
rather than on the local render. A step body that reads one way on the card and
another way in the manual is the failure this whole build exists to prevent, and
it is worth asking the service rather than asking ourselves.

The second check cannot be done against the spec alone, and that is the whole
difficulty. Documents get edited after they are published: an approved torque
change means the spec on disk no longer words the step the way either live
document words it. Asking "is the spec's sentence in both?" then answers *no*
for a pair in perfect agreement -- and would answer *no* just as loudly for a
manual reading 1.6 N·m beside a card reading 1.8.

So when the spec's wording is missing, the question changes to the one this
build actually makes a claim about: **do these two documents still say the same
thing?** The passage each document holds in that place is found by how much of
the original survives in it, and the two are then compared against each other,
with the difference printed -- `-1.6 +1.8` is a report somebody can act on and
"they disagree" is not.

Three answers, and the third one is load-bearing. A passage rewritten past
recognition in both documents is a `--`: there is nothing left tying either of
them to the original, and picking whichever paragraph scores highest would be
inventing a comparison rather than making one. A passage still verbatim in one
document and unrecognisable in the other is not a `--` -- it is the pair coming
apart as completely as it can, and it fails.

Each document is read back by its **durable id**, not exported out of its
session. That is not a performance choice. Export renders whatever the session
is focused on, and focus is not owned by whoever opened the session -- so an
export can return a perfectly valid document that is not the one asked for, and
this module would then report on it at length and in detail. Naming the document
removes the failure mode rather than checking for it afterwards.

Nothing here is billed either way.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import unescape
from urllib.parse import urlparse

from manualbuilder import projections as pj
from manualbuilder import session
from manualbuilder.spec import Spec

#: The two role names, matching `Publication.name_for`, because that is what the
#: caller has in its hand when it exports.
MANUAL = "manual"
CARD = "quick-start card"

OK = "ok"
FAIL = "FAIL"
#: Checked, and the answer is that it can no longer be checked. Distinct from a
#: pass: reporting "ok" here would be claiming something this cannot see.
MOOT = "--"


@dataclass(frozen=True)
class Finding:
    status: str
    check: str
    detail: str


_DROP = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_BLOCK = re.compile(r"<(p|li|td|th|h[1-6]|figcaption|blockquote)\b[^>]*>(.*?)</\1>", re.I | re.S)

#: How close a passage has to be to the spec's wording to be treated as that
#: passage, edited. Chosen well above what unrelated steps score against each
#: other and well below what a changed figure costs: swapping 1.2 for 1.6 in a
#: 40-word instruction is a ratio around 0.99, and the nearest *different* step
#: in this document set scores under 0.5. `test_verify.py` pins both ends.
MATCH = 0.75


def text_of(html: str) -> str:
    """The words a reader sees, with markup and whitespace differences gone.

    `<script>` and `<style>` come out before the tags do. A document read by id
    is the stored body and carries neither, but an export of the same document
    arrives wrapped in a full HTML document with several hundred bytes of the
    service's own CSS in it -- and a comparison that searched that would be
    matching stylesheet text against manual text.
    """
    return _WS.sub(" ", unescape(_TAG.sub(" ", _DROP.sub(" ", html)))).strip()


def _needle(text: str) -> str:
    return _WS.sub(" ", unescape(text)).strip()


def passages(html: str) -> list[str]:
    """Every block-level element's text, as a list.

    `text_of` flattens a document so a passage can be looked for in it. This
    keeps the passages apart, so the one that *used* to be a given instruction
    can be found again after somebody edited it.
    """
    body = _DROP.sub(" ", html)
    found = (_needle(_TAG.sub(" ", m.group(2))) for m in _BLOCK.finditer(body))
    return [text for text in found if text]


def closest(needle: str, candidates: list[str]) -> tuple[str, float]:
    """The candidate most like `needle`, and how like it it is.

    Public rather than the private helper it started as: `session.py`'s
    `excusably_empty` reuses it too, to judge whether a document that
    proposed nothing ever held the fact that changed elsewhere, at the same
    threshold this module is calibrated against.
    """
    best, score = "", 0.0
    for candidate in candidates:
        ratio = SequenceMatcher(None, needle, candidate).ratio()
        if ratio > score:
            best, score = candidate, ratio
    return best, score


def _difference(one: str, other: str, limit: int = 8) -> str:
    """The words that differ, for a message somebody has to act on.

    "the two have come apart" is a true sentence nobody can do anything with.
    `-1.2 +1.6` is the whole story.
    """
    words = [
        w
        for w in difflib.unified_diff(one.split(), other.split(), lineterm="", n=0)
        if w[:1] in "+-" and not w.startswith(("+++", "---"))
    ]
    shown = " ".join(words[:limit])
    return shown + (" …" if len(words) > limit else "")


def image_findings(served: dict[str, str], images: dict[str, str], spec: Spec) -> list[Finding]:
    """Every figure in every served document, against the URL recorded for it."""
    captions = pj.captions(spec)
    expected = {
        MANUAL: pj.captions_in(pj.manual_blocks(spec)),
        CARD: pj.captions_in(pj.quick_start_blocks(spec)),
    }

    out: list[Finding] = []
    for role, html in served.items():
        found = session.images_in(html)
        wanted = expected.get(role, {})
        if len(found) != len(wanted):
            out.append(
                Finding(
                    FAIL,
                    f"{role}: figure count",
                    f"{len(found)} figure(s) served, {len(wanted)} expected -- a "
                    f"figure has been added or lost",
                )
            )

        for alt, src in found:
            image_id = captions.get(alt)
            if image_id is None:
                out.append(
                    Finding(
                        FAIL,
                        f"{role}: unknown figure",
                        f"alt text {alt!r} matches no caption in the spec, so there "
                        f"is nothing to check it against",
                    )
                )
                continue
            recorded = images.get(image_id)
            if not recorded:
                out.append(
                    Finding(
                        MOOT,
                        f"{role}: {image_id}",
                        "no URL recorded for this diagram in published.json",
                    )
                )
                continue
            if urlparse(src).path == urlparse(recorded).path:
                out.append(
                    Finding(OK, f"{role}: {image_id}", urlparse(recorded).path.rsplit("/", 1)[-1])
                )
            else:
                out.append(
                    Finding(
                        FAIL,
                        f"{role}: {image_id}",
                        f"served {urlparse(src).path.rsplit('/', 1)[-1]}, "
                        f"published {urlparse(recorded).path.rsplit('/', 1)[-1]} -- "
                        f"this document is showing an older drawing",
                    )
                )
    return out


def pair_findings(served: dict[str, str], spec: Spec) -> list[Finding]:
    """Every instruction and fix the card shares with the manual, on both."""
    if MANUAL not in served or CARD not in served:
        return [Finding(MOOT, "pair", "both documents are needed to compare them")]

    manual, card = text_of(served[MANUAL]), text_of(served[CARD])
    blocks = {MANUAL: passages(served[MANUAL]), CARD: passages(served[CARD])}
    out: list[Finding] = []
    items = [("step", step.id, step.body) for step in spec.quick_start()] + [
        ("fix", fault.id, fault.fix) for fault in spec.quick_start_troubleshooting()
    ]

    for kind, item_id, body in items:
        needle = _needle(body)
        in_manual, in_card = needle in manual, needle in card
        label = f"{kind} {item_id}"

        if in_manual and in_card:
            out.append(Finding(OK, label, "word for word in both documents"))
            continue

        # The spec's wording is not in one or both of them, which on its own
        # says nothing: an approved edit moves the live documents away from the
        # spec that describes them, and that is the normal state of a published
        # pair. So the question stops being "does the spec's sentence appear"
        # and becomes "do these two documents still say the same thing" -- which
        # is the claim this build actually makes. The passage each document has
        # in that place is found by how close it still is to the original, and
        # the two are compared against each other.
        best = {role: closest(needle, blocks[role]) for role in (MANUAL, CARD)}
        lost = [role for role, (_, score) in best.items() if score < MATCH]
        if lost and (in_manual or in_card):
            # One document still has the sentence exactly as published and the
            # other has nothing resembling it. That is not an edit this cannot
            # follow, it is the passage being dropped or rewritten out of one of
            # them -- the pair coming apart in the most complete way available.
            here = MANUAL if in_manual else CARD
            out.append(
                Finding(
                    FAIL,
                    label,
                    f"in the {here} as published, and nothing in the "
                    f"{lost[0]} resembles it any more -- dropped or rewritten",
                )
            )
            continue
        if lost:
            out.append(
                Finding(
                    MOOT,
                    label,
                    f"nothing in the {' or the '.join(lost)} is recognisably this "
                    f"any more, so the two cannot be compared on it",
                )
            )
            continue

        theirs, ours = best[MANUAL][0], best[CARD][0]
        if theirs == ours:
            out.append(
                Finding(
                    OK,
                    label,
                    "edited since publish, and both documents carry the same new "
                    f"wording ({_difference(needle, ours, limit=4) or 'reformatted'})",
                )
            )
        else:
            out.append(
                Finding(
                    FAIL,
                    label,
                    f"the two documents word this differently -- manual vs card: "
                    f"{_difference(theirs, ours)}",
                )
            )
    return out


def verify(served: dict[str, str], images: dict[str, str], spec: Spec) -> list[Finding]:
    return image_findings(served, images, spec) + pair_findings(served, spec)


def failed(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.status == FAIL]


__all__ = [
    "CARD",
    "FAIL",
    "MANUAL",
    "MATCH",
    "MOOT",
    "OK",
    "Finding",
    "closest",
    "failed",
    "image_findings",
    "pair_findings",
    "passages",
    "text_of",
    "verify",
]
