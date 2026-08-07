"""Cover-page text is grammatical and grounded in the exhibit — never a list of
truncated keyword stems (the defect this locks down: the old writer emitted
"Evidences twent, marri, and daugh relevant to this application.").

The old writer fed stemmed keywords straight onto the cover page. The
regression assertion is deliberately structural — a complete, factual sentence
that names the exhibit's own field values or quotes its own clause — over the
whole real sample pile, plus golden checks on the most representative
structured and prose documents.
"""

from __future__ import annotations

import re
from pathlib import Path

from exhibit import proposals
from exhibit.loader import load_evidence

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "sample" / "evidence"

# Every sample exhibit, loaded exactly the way the engine loads them (the same
# mix of .pdf, .docx, .md and .txt the CLI would assemble), plus the late
# insertion the demo workflow adds.
_SAMPLE = load_evidence(
    [str(p) for p in sorted(EVIDENCE.iterdir())]
    + [str(ROOT / "sample" / "late" / "medical_report.txt")]
)


def _cover(item) -> str:
    return proposals._default_cover_writer(
        proposals._human_title(item.source), item.text
    )


def _by_name() -> dict[str, object]:
    return {Path(it.source).name: it for it in _SAMPLE}


def _is_grammatical(cover: str) -> bool:
    """The cover reads as one complete, factual sentence."""
    if not cover.startswith("Evidences"):
        return False
    if not (cover.endswith(".") or cover.endswith("”")):
        return False
    # The old defect's exact phrasing — bare stems joined by commas into
    # "Evidences balan, depos, and trans relevant to this application." A
    # grammatical cover names whole field values or quotes a whole clause.
    if "relevant to this application" in cover:
        return False
    return len(cover.split()) >= 5


def test_every_sample_cover_is_grammatical():
    for item in _SAMPLE:
        cover = _cover(item)
        assert _is_grammatical(cover), cover


def test_structured_documents_name_their_field_values():
    """Passports, tax returns, leases and certificates are summarised by their
    real field: value pairs — never stems of the words in them."""
    names = _by_name()

    passport = _cover(names["passport.pdf"])
    assert "S4827371" in passport          # the actual passport number
    assert "Date of Birth" in passport
    assert "14 MAR 1994" in passport

    tax = _cover(names["joint_tax_return.txt"])
    assert "Total Income: $100,300.00" in tax
    assert "Wages" in tax

    lease = _cover(names["joint_lease.txt"])
    assert "Monthly Rent" in lease and "$1,750" in lease

    marriage = _cover(names["marriage_certificate.docx"])
    assert "2022/BR/4412" in marriage


def test_prose_documents_quote_their_own_voice():
    """Letters and reports quote a real sentence from the document, in its own
    words — not a keyword soup built from it."""
    names = _by_name()

    letters = _cover(names["support_letters.md"])
    assert "married since December 2022" in letters

    medical = _cover(names["medical_report.txt"])
    assert "attended a routine health consultation" in medical


def test_no_truncated_stems_on_any_cover():
    """No cover may contain a 5-character stem of a longer word — the exact
    corruption the old writer produced ("twent", "marri", "daugh")."""
    stems = {"twent", "marri", "daugh", "balan", "depos", "trans"}
    for item in _SAMPLE:
        cover = _cover(item)
        for stem in stems:
            assert not re.search(rf"\b{stem}\b", cover), cover


def test_golden_covers_for_structured_and_prose_paths():
    """Lock the exact grammatical output of the two render paths so any drift
    back towards stem concatenation fails loudly."""
    names = _by_name()
    assert _cover(names["passport.pdf"]) == (
        "Evidences Passport No.: S4827371, Date of Birth: 14 MAR 1994, "
        "Date of Issue: 02 JAN 2023."
    )
    assert _cover(names["medical_report.txt"]) == (
        "Evidences: “Reyansh Sharma attended a routine health consultation "
        "on 10 May 2026.”"
    )
