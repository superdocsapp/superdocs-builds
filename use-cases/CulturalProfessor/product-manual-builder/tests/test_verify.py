"""What `verify` sees when the documents on the service are wrong.

`verify` is the command that reads the pair back off the service and says
whether it is what this program recorded publishing. A verification step that
can only ever print green is worse than none, so every test here is a served
document that is broken in a specific way, and the check has to find it.

The served HTML is built here rather than fetched: the point is what `verify`
concludes from a document, and a document is a string.
"""
from __future__ import annotations

from manualbuilder import projections as pj, verify as vf

BASE = "https://storage.example/img"


def served(spec, role: str, images: dict[str, str]) -> str:
    """A document as the service hands it back: wrapped, styled, and signed.

    Every difference that bit a real run is reproduced -- the export wrapper and
    its stylesheet, and the ~750-character signed query the service appends to
    every image URL when it serves one.
    """
    blocks = (pj.manual_blocks if role == vf.MANUAL else pj.quick_start_blocks)
    body = pj.render(blocks(spec, images))
    signed = body.replace(".svg\"", ".svg?X-Goog-Expires=86400&X-Goog-Signature="
                          + "a" * 512 + "\"")
    return ("<!DOCTYPE html><html><head><style>body { font-size: 11pt; }"
            "h1 { font-family: sans-serif; }</style></head><body>"
            + signed + "</body></html>")


def urls(spec) -> dict[str, str]:
    return {image_id: f"{BASE}/{image_id.replace(':', '_')}.svg"
            for image_id in pj.image_ids(spec)}


def both(spec, images) -> dict[str, str]:
    return {vf.MANUAL: served(spec, vf.MANUAL, images),
            vf.CARD: served(spec, vf.CARD, images)}


# ------------------------------------------------------------- the images --

def test_a_correctly_published_pair_passes(spec):
    findings = vf.verify(both(spec, urls(spec)), urls(spec), spec)
    assert not vf.failed(findings)
    assert all(finding.status == vf.OK for finding in findings), \
        [f for f in findings if f.status != vf.OK]


def test_the_signature_the_service_appends_is_not_a_different_image(spec):
    """The whole reason this compares paths. The served `src` never equals the
    published URL as a string, so a string comparison fails every correct
    document -- which is what happened on the first live run."""
    images = urls(spec)
    manual = both(spec, images)[vf.MANUAL]
    assert "X-Goog-Signature" in manual, "the fixture must reproduce the signing"
    assert not vf.failed(vf.image_findings({vf.MANUAL: manual}, images, spec))


def test_a_document_still_showing_the_old_drawing_is_caught(spec):
    """The live failure `verify` exists for. `sync` swapped the manual's figures
    and left the card's, and every other signal said the run was clean."""
    images = urls(spec)
    stale = dict(images, **{pj.BREAKDOWN: f"{BASE}/breakdown-v1.svg"})
    pair = {vf.MANUAL: served(spec, vf.MANUAL, images),
            vf.CARD: served(spec, vf.CARD, stale)}

    bad = vf.failed(vf.image_findings(pair, images, spec))
    assert len(bad) == 1
    assert bad[0].check == f"{vf.CARD}: {pj.BREAKDOWN}"
    assert "older drawing" in bad[0].detail


def test_a_figure_that_lost_its_image_is_caught(spec):
    """A figure served with no `<img>` at all -- the diagram silently gone."""
    images = urls(spec)
    pair = both(spec, images)
    pair[vf.CARD] = pair[vf.CARD].replace("<img", "<span", 1)

    bad = vf.failed(vf.image_findings(pair, images, spec))
    assert any("figure count" in finding.check for finding in bad)


def test_a_url_that_was_never_published_is_caught(spec):
    """Not "the src changed", but "the src is not the file we uploaded". A
    plausible-looking URL is the likeliest wrong answer here."""
    images = urls(spec)
    invented = dict(images, **{"step:laser": f"{BASE}/step_laser-v9.svg"})
    bad = vf.failed(vf.image_findings(
        {vf.MANUAL: served(spec, vf.MANUAL, invented)}, images, spec))
    assert len(bad) == 1 and "step:laser" in bad[0].check


# --------------------------------------------------------------- the pair --

def test_the_two_documents_disagreeing_is_caught(spec):
    """The drift this build exists to prevent, found on the served documents
    rather than on the local render."""
    images = urls(spec)
    pair = both(spec, images)
    rails = next(step for step in spec.quick_start() if step.id == "rails")
    # The manual corrected, the card left behind: exactly what happens when
    # somebody edits one document and forgets the other.
    pair[vf.MANUAL] = pair[vf.MANUAL].replace(rails.body,
                                              rails.body.replace("1.2", "1.6"))

    bad = vf.failed(vf.pair_findings(pair, spec))
    assert len(bad) == 1
    assert bad[0].check == "step rails"
    # And it says what the difference *is*, because "they disagree" is a true
    # sentence nobody can act on. Read manual-first: `-` is the manual's
    # wording, `+` is the card's.
    assert "word this differently" in bad[0].detail
    assert "-1.6" in bad[0].detail and "+1.2" in bad[0].detail


def test_a_fix_dropped_from_the_card_is_caught(spec):
    """Not an edit this cannot follow -- the passage gone out of one document
    altogether, which is the pair coming apart as completely as it can."""
    images = urls(spec)
    pair = both(spec, images)
    fault = spec.quick_start_troubleshooting()[0]
    pair[vf.CARD] = pair[vf.CARD].replace(fault.fix, "see the manual")

    bad = vf.failed(vf.pair_findings(pair, spec))
    assert len(bad) == 1 and bad[0].check == f"fix {fault.id}"
    assert "dropped or rewritten" in bad[0].detail


def test_an_edit_applied_to_both_is_a_pass(spec):
    """The case the spec cannot answer on its own. An approved edit moves the
    live documents away from the spec that describes them, so neither one still
    reads the way the spec words it -- and asking the spec gets "I cannot see
    this any more" for a pair that is in perfect agreement. So the two documents
    are compared to each other instead, and this is a pass with the edit named."""
    images = urls(spec)
    pair = both(spec, images)
    rails = next(step for step in spec.quick_start() if step.id == "rails")
    moved = rails.body.replace("1.2", "1.6")
    pair = {role: html.replace(rails.body, moved) for role, html in pair.items()}

    findings = vf.pair_findings(pair, spec)
    assert not vf.failed(findings)
    rails_finding = next(f for f in findings if f.check == "step rails")
    assert rails_finding.status == vf.OK
    assert "both documents carry the same new wording" in rails_finding.detail
    assert "+1.6" in rails_finding.detail


def test_an_edit_applied_to_both_but_differently_is_caught(spec):
    """The failure the previous version of this check could not see at all. Both
    documents were edited, so neither matches the spec, so the old answer was
    "cannot tell" -- for a manual reading 1.6 N·m and a card reading 1.8."""
    images = urls(spec)
    pair = both(spec, images)
    rails = next(step for step in spec.quick_start() if step.id == "rails")
    pair[vf.MANUAL] = pair[vf.MANUAL].replace(rails.body,
                                              rails.body.replace("1.2", "1.6"))
    pair[vf.CARD] = pair[vf.CARD].replace(rails.body,
                                          rails.body.replace("1.2", "1.8"))

    bad = vf.failed(vf.pair_findings(pair, spec))
    assert len(bad) == 1 and bad[0].check == "step rails"
    assert "-1.6" in bad[0].detail and "+1.8" in bad[0].detail


def test_a_passage_edited_past_recognition_is_not_guessed_at(spec):
    """The limit of matching by similarity, and it has to stay a `--`. If both
    documents rewrote the step from scratch there is nothing left tying either
    of them to the original, and picking whichever paragraph scores highest
    would be inventing a comparison."""
    images = urls(spec)
    pair = both(spec, images)
    rails = next(step for step in spec.quick_start() if step.id == "rails")
    pair = {role: html.replace(rails.body, "Refer to the assembly video.")
            for role, html in pair.items()}

    findings = vf.pair_findings(pair, spec)
    assert not vf.failed(findings)
    rails_finding = next(f for f in findings if f.check == "step rails")
    assert rails_finding.status == vf.MOOT
    assert "cannot be compared" in rails_finding.detail


def test_a_different_step_is_never_mistaken_for_an_edited_one(spec):
    """The threshold has to sit above what unrelated steps score against each
    other, or a deleted passage gets silently matched to a neighbouring one and
    reported as drift -- or worse, as agreement."""
    rails = next(step for step in spec.quick_start() if step.id == "rails")
    others = [step.body for step in spec.quick_start() if step.id != "rails"]
    best, score = vf._closest(rails.body, others)
    assert score < vf.MATCH, f"a different step scored {score:.2f}: {best[:60]!r}"

    edited = rails.body.replace("1.2", "1.6")
    assert vf._closest(rails.body, [edited])[1] > vf.MATCH


def test_the_services_stylesheet_is_not_searched_for_document_text(spec):
    """The export arrives wrapped in a full HTML document with several hundred
    bytes of CSS in it. Left in, it is text that no reader sees being searched
    as though it were the document."""
    text = vf.text_of(served(spec, vf.CARD, urls(spec)))
    assert "font-family" not in text and "11pt" not in text
    assert spec.quick_start()[0].body in text


def test_a_missing_document_is_not_a_silent_pass(spec):
    findings = vf.pair_findings({vf.MANUAL: "<p>alone</p>"}, spec)
    assert [finding.status for finding in findings] == [vf.MOOT]
