"""Tests. None require an API key and none cost an operation.

These do not assert that the fake returns what it was told to return. Each one
injects a fault whose ground truth is known and asserts the comparator reports
that fault, only in the cases where the pathology exists, and nowhere else.
A benchmark whose measuring instrument is untested measures nothing.
"""

from __future__ import annotations

import json
import os
import re

import pytest

from tablebench import compare, extract
from tablebench.client import BudgetExceeded, FakeClient, Ledger
from tablebench.corpus import cases as case_mod
from tablebench.corpus.generate import write_docx
from tablebench.run import main as run_main, run_case

# Cases that actually contain each pathology, so a detector can be checked for
# false negatives AND false positives.
HAS_MERGE = {"merge_horizontal_header", "merge_vertical_label", "merge_l_shaped",
             "merge_full_row_divider", "merge_containing_nested",
             "header_two_level", "header_three_level", "header_repeat_flag"}
HAS_NESTED = {"merge_containing_nested", "nested_simple", "nested_two_deep",
              "nested_side_by_side"}


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    d = tmp_path_factory.mktemp("corpus")
    return {c.id: write_docx(c, str(d / f"{c.id}.docx")) for c in case_mod.CASES}


# --------------------------------------------------------------------------
# corpus and extraction
# --------------------------------------------------------------------------

def test_every_case_generates_a_readable_docx(corpus):
    assert len(corpus) == len(case_mod.CASES)
    for cid, path in corpus.items():
        assert os.path.getsize(path) > 0
        doc = extract.from_docx(path)
        assert doc.tables, f"{cid} produced no table"


def test_spans_survive_extraction(corpus):
    doc = extract.from_docx(corpus["merge_l_shaped"])
    t = doc.tables[0]
    assert t.cell_at(0, 0).row_span == 2          # Asset, merged down
    assert t.cell_at(0, 1).col_span == 2          # Planned, merged across
    assert t.cell_at(3, 0).col_span == 4          # full-width divider
    # A span is not the same cell repeated: anchors are unique.
    assert t.cell_at(0, 1) is t.cell_at(0, 2)


def test_nested_tables_are_reached_and_not_flattened(corpus):
    doc = extract.from_docx(corpus["nested_two_deep"])
    outer = doc.tables[0].cell_at(1, 1)
    assert len(outer.nested) == 1
    inner = outer.nested[0].cell_at(0, 1)
    assert len(inner.nested) == 1, "second level of nesting was lost"
    assert "0.72" in inner.nested[0].cell_at(1, 1).text


def test_pathological_numbers_are_character_exact(corpus):
    t = extract.from_docx(corpus["num_negative_parentheses"]).tables[0]
    assert t.cell_at(1, 1).text == "(12,400.00)"
    assert t.cell_at(3, 1).text == "\u2014", "em dash must not become a hyphen"
    t2 = extract.from_docx(corpus["num_leading_zero_ids"]).tables[0]
    assert t2.cell_at(1, 1).text == "0007", "leading zeros must not be dropped"


# --------------------------------------------------------------------------
# the comparator
# --------------------------------------------------------------------------

def test_control_roundtrip_is_lossless(corpus):
    """With no fault injected the pipeline must report nothing.

    If this drifts, every other detection result is unattributable noise.
    """
    fc = FakeClient(Ledger(cap=999))
    for cid, path in corpus.items():
        before = extract.from_docx(path)
        fc.upload(path, cid)
        out = fc.export(cid, f"/tmp/tfb-control/{cid}.docx")
        assert compare.compare(before, extract.from_docx(out)) == [], cid


@pytest.mark.parametrize("fault,applies_to", [
    ("flatten_merges", HAS_MERGE),
    ("drop_nested", HAS_NESTED),
])
def test_structural_faults_are_caught_where_they_apply(corpus, fault, applies_to):
    fc = FakeClient(Ledger(cap=999), fault=fault)
    detected = set()
    for cid, path in corpus.items():
        before = extract.from_docx(path)
        fc.upload(path, cid)
        out = fc.export(cid, f"/tmp/tfb-{fault}/{cid}.docx")
        if compare.compare(before, extract.from_docx(out)):
            detected.add(cid)
    missed = applies_to - detected
    assert not missed, f"{fault} went undetected in {sorted(missed)}"


def test_numeric_fault_is_caught_and_named(corpus):
    fc = FakeClient(Ledger(cap=999), fault="strip_trailing_zero")
    path = corpus["num_trailing_zeros"]
    before = extract.from_docx(path)
    fc.upload(path, "n")
    out = fc.export("n", "/tmp/tfb-num/x.docx")
    findings = compare.compare(before, extract.from_docx(out))
    codes = {f.code for f in findings}
    assert "cell_text" in codes
    assert any("1.23" in f.actual for f in findings), \
        "the comparator saw a change but did not report the changed value"


def test_untouched_body_text_is_an_invariant(corpus):
    fc = FakeClient(Ledger(cap=999), fault="rewrite_body")
    path = corpus["nested_simple"]
    before = extract.from_docx(path)
    fc.upload(path, "b")
    out = fc.export("b", "/tmp/tfb-body/x.docx")
    findings = compare.compare(before, extract.from_docx(out))
    assert any(f.code == "body_paragraphs" for f in findings), \
        "prose outside the table changed and was not reported"


def test_target_cell_is_exempt_but_its_neighbours_are_not(corpus):
    """The asymmetry that defines the measurement."""
    case = case_mod.BY_ID["merge_horizontal_header"]
    before = extract.from_docx(corpus[case.id])
    after = extract.from_docx(corpus[case.id])

    tgt = after.tables[0].cell_at(*case.target[1:])
    tgt.paragraphs = ["1,099.40"]
    assert compare.compare(before, after, target=case.target) == [], \
        "changing the target cell must not be a finding"

    neighbour = after.tables[0].cell_at(case.target[1], case.target[2] - 1)
    neighbour.paragraphs = ["tampered"]
    findings = compare.compare(before, after, target=case.target)
    assert [f.code for f in findings] == ["cell_text"], \
        "changing a neighbour must be a finding, and only that one"


def test_findings_are_attributed_between_edit_and_roundtrip():
    f1 = compare.Finding("content", "cell_text", "table[0] cell(1, 1)", "a", "b")
    f2 = compare.Finding("structural", "col_span", "table[0] cell(0, 1)", "2", "1")
    by_edit, by_rt = compare.attribute([f1, f2], control_findings=[f2])
    assert by_edit == [f1] and by_rt == [f2]


# --------------------------------------------------------------------------
# honesty, budget, resumption
# --------------------------------------------------------------------------

def test_error_is_reported_as_error_not_as_failure(corpus):
    class Broken(FakeClient):
        def edit(self, *a, **k):
            raise RuntimeError("simulated upstream 502")

    rec = run_case(case_mod.BY_ID["nested_simple"],
                   Broken(Ledger(cap=99)), "/tmp/tfb-err")
    assert rec["verdict"] == compare.ERROR
    assert rec["verdict"] != compare.FAIL
    assert "502" in rec["error"]


def test_unverifiable_is_distinct_from_pass():
    assert compare.verdict(None, []) == compare.UNVERIFIABLE
    assert compare.verdict(True, []) == compare.PASS
    assert compare.verdict(False, []) == compare.FAIL


def test_budget_cap_stops_before_the_spend_not_after():
    led = Ledger(cap=2)
    led.charge("chat")
    led.charge("chat")
    with pytest.raises(BudgetExceeded):
        led.charge("chat")
    assert led.spent == 2, "the ledger must not record a spend it refused"


def test_free_stages_do_not_consume_operations():
    led = Ledger(cap=1)
    for stage in ("upload", "approve", "export"):
        led.charge(stage)
    assert led.spent == 0


def test_run_is_resumable_after_being_killed(tmp_path):
    out = str(tmp_path / "r")
    run_main(["--mode", "dry", "--max-ops", "3", "--out", out])
    state = json.load(open(os.path.join(out, "state.json")))
    first = len(state["cases"])
    assert 0 < first < len(case_mod.CASES), "budget stop did not halt the run"

    run_main(["--mode", "dry", "--max-ops", "99", "--out", out, "--resume"])
    state2 = json.load(open(os.path.join(out, "state.json")))
    assert len(state2["cases"]) == len(case_mod.CASES)
    for cid in list(state["cases"])[:first]:
        assert state2["cases"][cid]["seconds"] == state["cases"][cid]["seconds"], \
            f"{cid} was re-run instead of resumed, re-spending its operation"


def test_proposed_changes_get_the_second_parse():
    """The documented integrator trap: content arrives JSON-encoded."""
    from tablebench.client import SuperDocsClient
    job = {"metadata": {"pending_changes": [
        {"change_id": "c1", "content": json.dumps({"chunk_id": "p3", "html": "<p>x</p>"})},
        {"change_id": "c2", "content": "{not valid json"},
    ]}}
    parsed = SuperDocsClient._pending(job)
    assert parsed[0]["content"]["chunk_id"] == "p3", "second parse not applied"
    assert parsed[1].get("content_parse_failed") is True, \
        "an unparseable change must be flagged, not silently passed through"


def test_no_credential_ever_reaches_an_output_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_live_THIS_MUST_NEVER_APPEAR")
    out = str(tmp_path / "r")
    run_main(["--mode", "dry", "--limit", "3", "--out", out])
    for root, _, files in os.walk(out):
        for name in files:
            if name.endswith((".json", ".md")):
                body = open(os.path.join(root, name), encoding="utf-8").read()
                assert not re.search(r"sk_[A-Za-z0-9_]{4,}", body), \
                    f"a key-shaped string reached {name}"


def test_report_states_its_own_limits(tmp_path):
    out = str(tmp_path / "r")
    run_main(["--mode", "dry", "--limit", "2", "--out", out])
    report = open(os.path.join(out, "report.md")).read()
    assert "Limits of this measurement" in report
    assert "not measurable" in report or "never FAIL" in report


def test_a_dry_record_never_satisfies_a_live_resume(tmp_path):
    """Regression: --resume once skipped live work because dry records held
    those slots, and counted simulated operations against the live cap. A
    simulation is not evidence about the API and must not stand in for it."""
    out = str(tmp_path / "r")
    run_main(["--mode", "dry", "--limit", "3", "--out", out])
    path = os.path.join(out, "state.json")
    state = json.load(open(path))
    assert {r["mode"] for r in state["cases"].values()} == {"dry"}

    # Pretend one case was measured live, then resume in dry mode.
    victim = sorted(state["cases"])[0]
    state["cases"][victim]["mode"] = "live"
    state["cases"][victim]["seconds"] = -1.0
    json.dump(state, open(path, "w"))

    run_main(["--mode", "dry", "--limit", "3", "--out", out, "--resume"])
    after = json.load(open(path))
    assert after["cases"][victim]["seconds"] != -1.0, \
        "a live record was treated as a dry record and skipped"
    assert after["cases"][victim]["mode"] == "dry"


def test_simulated_operations_do_not_reserve_live_budget(tmp_path):
    out = str(tmp_path / "r")
    run_main(["--mode", "dry", "--limit", "5", "--max-ops", "5", "--out", out])
    state = json.load(open(os.path.join(out, "state.json")))
    assert sum(r["ops"] for r in state["cases"].values()) == 5
    # Every one of those ops is dry, so a live run starts from zero.
    live_prior = sum(r.get("ops", 0) for r in state["cases"].values()
                     if r.get("mode") == "live")
    assert live_prior == 0


def test_report_refuses_to_present_a_mixed_run_as_one(tmp_path):
    out = str(tmp_path / "r")
    run_main(["--mode", "dry", "--limit", "3", "--out", out])
    path = os.path.join(out, "state.json")
    state = json.load(open(path))
    state["cases"][sorted(state["cases"])[0]]["mode"] = "live"
    json.dump(state, open(path, "w"))

    run_main(["--mode", "dry", "--limit", "3", "--out", out, "--resume"])
    report = open(os.path.join(out, "report.md")).read()
    if "MIXED" in report:
        assert "not one run" in report


def test_an_instruction_naming_two_cells_exempts_both(corpus):
    """Regression: a two-figure instruction with one declared target reported
    the model for obeying it. A false finding is worse than no finding."""
    case = case_mod.BY_ID["merge_full_row_divider"]
    assert case.also_changes, "this case's instruction changes two cells"

    before = extract.from_docx(corpus[case.id])
    after = extract.from_docx(corpus[case.id])
    after.tables[0].cell_at(*case.target[1:]).paragraphs = ["46"]
    after.tables[0].cell_at(*case.also_changes[0][1:]).paragraphs = ["1,426.00"]

    exempt = [case.target, *case.also_changes]
    assert compare.compare(before, after, target=exempt) == [], \
        "both cells named in the instruction must be exempt"

    # And a third cell is still an invariant.
    after.tables[0].cell_at(2, 1).paragraphs = ["tampered"]
    assert [f.code for f in compare.compare(before, after, target=exempt)] == \
        ["cell_text"]


def test_every_case_exempts_as_many_cells_as_its_instruction_changes():
    """A guard against the same mistake in a case added later."""
    for c in case_mod.CASES:
        named = 1 + len(c.also_changes)
        # crude but effective: count 'to <value>' clauses in the instruction
        clauses = c.edit.lower().count(" to ")
        assert clauses <= named, (
            f"{c.id}: instruction appears to change {clauses} cells but only "
            f"{named} are exempt")


def test_shared_edges_resolve_the_same_way_every_time(corpus):
    """Regression: an interior rule is written by both adjacent cells. Without
    a precedence rule the winner depended on cell ordering, so a document
    could compare unequal to itself and produce findings that were artifacts."""
    doc = extract.from_docx(corpus["struct_shading_borders"])
    t = doc.tables[0]

    edges = t.border_edges()
    reversed_t = extract.from_docx(corpus["struct_shading_borders"]).tables[0]
    reversed_t.cells.reverse()
    assert reversed_t.border_edges() == edges, \
        "edge resolution depends on cell order"

    # The declared coloured rule must beat the inherited default it collides
    # with, not the other way round.
    assert edges[("h", 2, 1)] == "single/18/2E7D32"
    assert edges[("h", 4, 1)] == "single/18/C62828"


def test_capture_does_not_call_a_withheld_measurement_a_survival():
    """Regression. The summary said text_direction 'survives ingest, lost on
    export'. It does not survive ingest -- plain HTML has no property for it,
    so the HTML stage withholds it and measures nothing either way. Reporting
    withheld as intact asserts something the evidence cannot support, and it
    contradicted the written bug report it was attached to."""
    from tablebench import capture, compare
    assert "text_direction" in compare.HTML_UNREPRESENTABLE
    assert "border_edge" in compare.HTML_UNREPRESENTABLE
    # header_rows was withheld until the API turned out to return a real
    # <thead>; it is measurable and must not be withheld.
    assert "header_rows" not in compare.HTML_UNREPRESENTABLE
    src = open(capture.__file__, encoding="utf-8").read()
    assert "HTML_UNREPRESENTABLE" in src, \
        "capture must exclude withheld codes from its stage attribution"
