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

That second check has three answers and not two, which is the honest shape.
Documents get edited after they are published: an approved torque change means
the spec on disk no longer words the step the way the live documents word it.
Text found in *neither* document is not a failure -- it is a check that can no
longer see what it was looking at, and it says so. Text found in exactly *one*
is drift, and that is a failure.

No quota is spent here. Exports are free, which is the whole reason the
verification path leans on them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import urlparse

from manualbuilder import projections as pj, session
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


def text_of(html: str) -> str:
    """The words a reader sees, with markup and whitespace differences gone.

    The service wraps an export in a full HTML document with its own
    stylesheet, so `<style>` has to come out before the tags do or a comparison
    is searching several hundred bytes of CSS as well.
    """
    return _WS.sub(" ", unescape(_TAG.sub(" ", _DROP.sub(" ", html)))).strip()


def _needle(text: str) -> str:
    return _WS.sub(" ", unescape(text)).strip()


def image_findings(served: dict[str, str], images: dict[str, str],
                   spec: Spec) -> list[Finding]:
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
            out.append(Finding(
                FAIL, f"{role}: figure count",
                f"{len(found)} figure(s) served, {len(wanted)} expected -- a "
                f"figure has been added or lost"))

        for alt, src in found:
            image_id = captions.get(alt)
            if image_id is None:
                out.append(Finding(
                    FAIL, f"{role}: unknown figure",
                    f"alt text {alt!r} matches no caption in the spec, so there "
                    f"is nothing to check it against"))
                continue
            recorded = images.get(image_id)
            if not recorded:
                out.append(Finding(
                    MOOT, f"{role}: {image_id}",
                    "no URL recorded for this diagram in published.json"))
                continue
            if urlparse(src).path == urlparse(recorded).path:
                out.append(Finding(
                    OK, f"{role}: {image_id}",
                    urlparse(recorded).path.rsplit("/", 1)[-1]))
            else:
                out.append(Finding(
                    FAIL, f"{role}: {image_id}",
                    f"served {urlparse(src).path.rsplit('/', 1)[-1]}, "
                    f"published {urlparse(recorded).path.rsplit('/', 1)[-1]} -- "
                    f"this document is showing an older drawing"))
    return out


def pair_findings(served: dict[str, str], spec: Spec) -> list[Finding]:
    """Every instruction and fix the card shares with the manual, on both."""
    if MANUAL not in served or CARD not in served:
        return [Finding(MOOT, "pair", "both documents are needed to compare them")]

    manual, card = text_of(served[MANUAL]), text_of(served[CARD])
    out: list[Finding] = []
    items = ([("step", step.id, step.body) for step in spec.quick_start()]
             + [("fix", fault.id, fault.fix)
                for fault in spec.quick_start_troubleshooting()])

    for kind, item_id, body in items:
        needle = _needle(body)
        in_manual, in_card = needle in manual, needle in card
        label = f"{kind} {item_id}"
        if in_manual and in_card:
            out.append(Finding(OK, label, "word for word in both documents"))
        elif not in_manual and not in_card:
            out.append(Finding(
                MOOT, label,
                "in neither document as the spec words it -- edited since "
                "publish; this does not prove the two still agree"))
        else:
            here = MANUAL if in_manual else CARD
            missing = CARD if in_manual else MANUAL
            out.append(Finding(
                FAIL, label,
                f"in the {here} but not the {missing} -- the two have come apart"))
    return out


def verify(served: dict[str, str], images: dict[str, str],
           spec: Spec) -> list[Finding]:
    return image_findings(served, images, spec) + pair_findings(served, spec)


def failed(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.status == FAIL]


__all__ = ["Finding", "MANUAL", "CARD", "OK", "FAIL", "MOOT", "text_of",
           "image_findings", "pair_findings", "verify", "failed"]
