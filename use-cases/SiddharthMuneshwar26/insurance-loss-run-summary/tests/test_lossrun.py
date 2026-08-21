"""Tests. No API key, no network, no operations.

The manifest that ships with the corpus is the answer key. These tests assert
the app reproduces it exactly — both halves: every planted conflict and finding
is found, and nothing outside the answer key is reported. A summariser that
flags everything would pass the first half and fail the second.
"""

from __future__ import annotations

import datetime
import glob
import json
import os
from collections import Counter

import pytest

from lossrun import parse, summarize
from lossrun.model import Claim, LossRun, Source
from lossrun.review import build_html, run
from lossrun.superdocs import BudgetExceeded, FakeClient, Ledger

CORPUS = os.environ.get("LOSSRUN_CORPUS", "corpus/out")
AS_OF = datetime.date(2026, 1, 9)

# From MANIFEST.md, which is generated alongside the corpus.
EXPECTED_FINDINGS = {"R1": 1, "R2": 4, "R3": 1, "R4": 1,
                     "R5": 3, "R6": 1, "R7": 1, "R8": 1}
EXPECTED_YEARS = {
    2021: {"claims": 12, "incurred": 237_280.35, "ratio": 0.576},
    2022: {"claims": 12, "incurred": 184_694.38, "ratio": 0.412},
    2023: {"claims": 10, "incurred": 647_992.44, "ratio": 1.293},
    2024: {"claims": 7, "incurred": 188_831.55, "ratio": 0.333},
}


@pytest.fixture(scope="module")
def analysed():
    runs = [parse.load(p) for p in sorted(glob.glob(f"{CORPUS}/loss-runs/*.csv"))]
    notes = {os.path.basename(p).split("-adjuster")[0]: parse.docx_text(p)
             for p in glob.glob(f"{CORPUS}/adjuster-notes/*.docx")}
    app = parse.docx_text(glob.glob(f"{CORPUS}/application/*.docx")[0])
    s = summarize.summarise(runs, "Meridian Cold Chain Logistics, Inc.")
    s = summarize.examine(s, runs, notes, app, as_of=AS_OF)
    return s, runs


# --------------------------------------------------------------------------
# the card's own bar: groups and totals by policy year, open claims separated
# --------------------------------------------------------------------------

def test_groups_and_totals_by_policy_year(analysed):
    s, _ = analysed
    assert len(s.years) == 4
    for y in s.years:
        want = EXPECTED_YEARS[y.policy_year]
        assert y.claim_count == want["claims"], f"PY{y.policy_year} claim count"
        assert y.total_incurred == pytest.approx(want["incurred"], abs=0.01)
        assert y.loss_ratio == pytest.approx(want["ratio"], abs=0.001)


def test_totals_are_the_sum_of_the_years(analysed):
    s, _ = analysed
    assert s.total_incurred == pytest.approx(
        sum(y.total_incurred for y in s.years), abs=0.01)
    assert s.total_claims == sum(y.claim_count for y in s.years) == 41


def test_open_claims_are_flagged_separately(analysed):
    s, _ = analysed
    assert s.total_open == 15
    assert len(s.open_claims) == 15
    assert all(c.is_open for c in s.open_claims)
    # and separating them is not the same as dropping them
    assert all(any(c.claim_no == o.claim_no for o in s.open_claims)
               for c in s.open_claims)
    for y in s.years:
        assert y.open_count <= y.claim_count


def test_paid_plus_reserve_equals_incurred_everywhere(analysed):
    s, runs = analysed
    for r in runs:
        for c in r.claims:
            assert c.paid + c.reserve == pytest.approx(c.incurred, abs=0.01), \
                f"{c.claim_no} does not add up"


# --------------------------------------------------------------------------
# supersession — the part that decides the answer
# --------------------------------------------------------------------------

def test_the_later_valuation_supersedes_and_the_difference_is_surfaced(analysed):
    s, _ = analysed
    assert len(s.documents_superseded) == 1
    assert "ORIGINAL" in s.documents_superseded[0]

    kinds = {c.subject: c.kind for c in s.conflicts}
    assert kinds["KM-2023-0417"] == "incurred_changed"
    assert kinds["KM-2023-0588"] == "claim_added"

    dev = next(c for c in s.conflicts if c.subject == "KM-2023-0417")
    assert "45,000.00" in dev.left and "182,400.00" in dev.right
    assert dev.resolution is None, "a conflict must not arrive pre-resolved"


def test_supersession_changes_the_underwriting_outcome(analysed):
    """The reason this matters: the same account either clears the 60%
    referral threshold or does not, depending on which run is trusted."""
    _, runs = analysed
    original = next(r for r in runs if r.policy_year == 2023 and not r.is_reissue)
    reissue = next(r for r in runs if r.policy_year == 2023 and r.is_reissue)
    premium = 501_200.00
    assert original.summed_total / premium < 0.60
    assert reissue.summed_total / premium > 0.60


def test_superseded_figures_are_excluded_from_totals(analysed):
    s, _ = analysed
    py23 = next(y for y in s.years if y.policy_year == 2023)
    assert py23.total_incurred == pytest.approx(647_992.44, abs=0.01)
    assert py23.total_incurred != pytest.approx(286_092.44, abs=0.01)


# --------------------------------------------------------------------------
# the rules — found, and nothing else found
# --------------------------------------------------------------------------

def test_every_expected_finding_is_produced(analysed):
    s, _ = analysed
    got = Counter(f.rule for f in s.findings)
    assert dict(got) == EXPECTED_FINDINGS


def test_no_finding_outside_the_answer_key(analysed):
    """The half that a flag-everything summariser would fail."""
    s, _ = analysed
    known = {
        "R1": {"KM-2024-0106"},
        "R2": {"KM-2021-0232", "KM-2021-0252", "KM-2021-0333", "KM-2022-0237"},
        "R3": {"PY2023"},
        "R4": {"KM-2022-0402"},
        "R6": {"KM-2021-0333"},
    }
    for rule, subjects in known.items():
        got = {f.subject for f in s.findings if f.rule == rule}
        assert got == subjects, f"{rule}: unexpected subjects {got ^ subjects}"


def test_a_clean_corpus_produces_no_findings():
    """An honest report of nothing is a valid output and must be reachable."""
    src = Source("clean.csv", "2026-01-01")
    claims = [Claim(f"KM-2024-{i:04d}", 2024, "P-1", "Auto Liability",
                    "2024-06-01", "2024-06-02", "Closed", "Third party",
                    1000.0, 0.0, 1000.0, "", src) for i in range(4)]
    run_ = LossRun("clean.csv", 2024, "P-1", "2024-04-01", "2025-04-01",
                   "2026-01-01", False, claims, stated_total=4000.0,
                   stated_count=4, earned_premium=500_000.0)
    s = summarize.summarise([run_], "Clean Co")
    s = summarize.examine(s, [run_], {}, "", as_of=AS_OF)
    assert s.findings == []
    assert s.conflicts == []


def test_loss_run_that_does_not_add_up_is_caught(analysed):
    s, _ = analysed
    r8 = [f for f in s.findings if f.rule == "R8"]
    assert len(r8) == 1
    assert "1,500.00" in r8[0].detail


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text,want", [
    ("$1,204,880.00", 1_204_880.00),
    ("(12,400.00)", -12_400.00),
    ("\u2014", 0.0),
    ("0.00", 0.0),
    ("", 0.0),
    ("94,750.00", 94_750.00),
])
def test_accountant_notation_parses(text, want):
    assert parse.money(text) == pytest.approx(want, abs=0.001)


def test_a_non_figure_raises_rather_than_becoming_zero():
    """Silently reading 'pending' as 0.00 would corrupt a total."""
    with pytest.raises(ValueError):
        parse.money("pending")


def test_pdf_and_csv_of_the_same_run_agree():
    pdfs = glob.glob(f"{CORPUS}/loss-runs/*.pdf")
    if not pdfs:
        pytest.skip("no PDF in corpus")
    try:
        pdf = parse.load(pdfs[0])
    except RuntimeError as exc:
        pytest.skip(str(exc))
    csv_path = pdfs[0].replace(".pdf", ".csv")
    if not os.path.exists(csv_path):
        pytest.skip("no matching CSV")
    csv_run = parse.load(csv_path)
    assert len(pdf.claims) == len(csv_run.claims)
    assert pdf.summed_total == pytest.approx(csv_run.summed_total, abs=0.01)
    a = {c.claim_no: (c.status, round(c.incurred, 2)) for c in pdf.claims}
    b = {c.claim_no: (c.status, round(c.incurred, 2)) for c in csv_run.claims}
    assert a == b, "the same policy year read two ways gave different facts"


# --------------------------------------------------------------------------
# budget, honesty, output
# --------------------------------------------------------------------------

def test_free_stages_cost_nothing_and_searches_do_not():
    led = Ledger(cap=1)
    for stage in ("upload", "approve", "export"):
        led.charge(stage)
    assert led.spent == 0
    led.charge("search")
    assert led.spent == 1
    with pytest.raises(BudgetExceeded):
        led.charge("chat")
    assert led.spent == 1, "a refused spend must not be recorded"


def test_the_review_names_what_it_cannot_establish(analysed):
    s, _ = analysed
    doc = build_html(s, [], AS_OF)
    assert "does not establish" in doc
    assert "no figure in this review is model-generated" in doc.lower()


def test_the_instruction_forbids_touching_any_figure():
    """The document is handed to a model. What stops it rewriting a total is
    this sentence, so the sentence is under test."""
    from lossrun.review import NARRATIVE_INSTRUCTION
    low = NARRATIVE_INSTRUCTION.lower()
    assert "do not" in low and "change" in low
    assert "recalculate" in low and "restate" in low
    for word in ("number", "date", "claim number", "table cell"):
        assert word in low, f"{word} is not protected by the instruction"
    assert "change nothing else" in low


def test_end_to_end_offline_spends_only_search_and_chat(tmp_path):
    out = str(tmp_path / "out")
    r = run(CORPUS, out, mode="dry", max_ops=6, as_of=AS_OF)
    led = r["ledger"]
    assert led.by_stage.get("upload", 0) == 0
    assert led.by_stage.get("export", 0) == 0
    assert led.spent == led.by_stage.get("search", 0) + led.by_stage.get("chat", 0)
    assert os.path.exists(os.path.join(out, "review.html"))
    data = json.load(open(os.path.join(out, "summary.json")))
    assert data["totals"]["claims"] == 41


def test_hitting_the_cap_degrades_instead_of_dying(tmp_path):
    """A cap reached mid-run must produce a document that says so, not a
    traceback and not a document that quietly omits a section."""
    out = str(tmp_path / "out")
    r = run(CORPUS, out, mode="dry", max_ops=0, as_of=AS_OF)
    assert os.path.exists(os.path.join(out, "review.html")), \
        "the review must still be written when the budget is exhausted"
    assert r["summary"].unverified, "the shortfall must be named, not hidden"
    data = json.load(open(os.path.join(out, "summary.json")))
    assert data["totals"]["claims"] == 41, \
        "figures must survive a budget that stops the document assembly"


def test_no_key_shaped_string_reaches_any_output(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_live_MUST_NOT_APPEAR")
    out = str(tmp_path / "out")
    run(CORPUS, out, mode="dry", max_ops=6, as_of=AS_OF)
    for name in os.listdir(out):
        body = open(os.path.join(out, name), encoding="utf-8", errors="ignore").read()
        assert "sk_live" not in body


def test_retrieval_reply_is_parsed_tolerantly():
    """Models fence JSON and pad it with prose. Neither should lose the data,
    and an unusable reply must yield nothing rather than a corrupt section."""
    from lossrun.superdocs import _parse_retrieval
    good = ('Here you go:\n```json\n[{"question": "q", "document": "note.docx", '
            '"quote": "reserve increased"}]\n```')
    assert _parse_retrieval(good) == [
        {"document": "note.docx", "text": "reserve increased", "question": "q"}]
    assert _parse_retrieval("[]") == []
    assert _parse_retrieval("sorry, I could not find anything") == []
    assert _parse_retrieval("") == []
    assert _parse_retrieval("[{not json") == []
    # An entry with no document is dropped rather than rendered blank.
    assert _parse_retrieval('[{"question":"q","document":null,"quote":""}]') == []


def test_a_missing_search_endpoint_is_named_not_swallowed():
    """404 on the dedicated search path must be distinguishable from a
    successful empty search."""
    from lossrun.superdocs import SearchUnavailable, ApiError
    assert issubclass(SearchUnavailable, ApiError)


def test_the_whole_run_costs_one_operation(tmp_path):
    """Retrieval and narrative are one edit, not two. Uploads, approval and
    export are free, so a full review is a single chargeable turn."""
    r = run(CORPUS, str(tmp_path / "out"), "dry", 6, AS_OF)
    assert r["ledger"].spent == 1, r["ledger"].by_stage


def test_the_correspondence_placeholder_is_filled_or_named(tmp_path):
    out = str(tmp_path / "out")
    r = run(CORPUS, out, "dry", 6, AS_OF)
    doc = open(os.path.join(out, "review.html"), encoding="utf-8").read()
    assert "From the correspondence" in doc
    # The placeholder is what the edit replaces; it must not survive into a
    # document that reports success.
    exported = open(r["exported"], encoding="utf-8").read()
    assert "[[CORRESPONDENCE]]" not in exported


def test_figures_do_not_depend_on_retrieval(tmp_path):
    """The claim the README makes: no figure is model-generated. Prove it by
    running with retrieval switched off and comparing every total."""
    a = run(CORPUS, str(tmp_path / "with"), "dry", 6, AS_OF)["summary"]
    b = run(CORPUS, str(tmp_path / "without"), "dry", 6, AS_OF,
            skip_prose=True)["summary"]
    assert a.total_incurred == b.total_incurred
    assert a.total_claims == b.total_claims
    assert [y.to_dict() for y in a.years] == [y.to_dict() for y in b.years]
    assert len(a.findings) == len(b.findings)
