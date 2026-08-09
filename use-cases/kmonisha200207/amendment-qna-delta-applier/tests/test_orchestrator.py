from pathlib import Path

from delta_applier.orchestrator import DeltaApplierRun, approve_all
from tests.fakes import FakeSuperDocsClient

FIXTURES = Path(__file__).parent.parent / "fixtures"
CONFIG = Path(__file__).parent.parent / "config" / "section_map.yaml"


def _make_run(client=None):
    client = client or FakeSuperDocsClient()
    run = DeltaApplierRun(client, str(CONFIG), session_id="test-session")
    run.ingest_baseline((FIXTURES / "solicitation.txt").read_text(encoding="utf-8"), "solicitation.txt")
    run.ingest_amendment((FIXTURES / "amendment_0001.txt").read_text(encoding="utf-8"), "amendment_0001.txt")
    run.ingest_qna((FIXTURES / "qna_0001.txt").read_text(encoding="utf-8"), "qna_0001.txt")
    return run, client


def test_deltas_and_impacts_computed_correctly():
    run, _ = _make_run()
    assert len(run.deltas) >= 5  # page limit, due date, 2x eval weight, added req, deleted req, exec summary clarification
    assert run.conflicts == []  # our bundled fixtures are self-consistent

    impacts = run.compute_impacts()
    assert impacts["SEC-VOL1-TECH"].order == "direct"
    assert impacts["SEC-COMPLIANCE-MATRIX"].order == "second_order"
    assert "SEC-VOL2-PASTPERF" in run.untouched_sections()


def test_full_run_auto_approve_applies_edits_and_proves_untouched_sections():
    run, client = _make_run()
    run.compute_impacts()
    run.load_proposal(str(FIXTURES / "proposal_draft.html"))

    review_items = run.run_all(approve_all)

    assert len(review_items) > 0
    assert all(item.approved for item in review_items)
    assert run.proposal_html_after != run.proposal_html_before

    for section_id in run.untouched_sections():
        assert f'data-section-id="{section_id}"' in run.proposal_html_after

    proofs = run.verify_untouched()
    for section_id, proof in proofs.items():
        assert proof.verified_untouched, f"{section_id} should be untouched but hash differs"

    # every review item must carry at least one citation back to a source paragraph
    for item in review_items:
        assert len(item.deltas) >= 1
        for d in item.deltas:
            assert d.source.paragraph_text


def test_rejecting_one_change_in_a_batch_does_not_discard_the_rest():
    run, client = _make_run()
    run.compute_impacts()
    run.load_proposal(str(FIXTURES / "proposal_draft.html"))

    rejected_change_ids = set()

    def reject_first_approve_rest(items):
        decisions = {}
        for i, item in enumerate(items):
            approved = i != 0
            if not approved:
                rejected_change_ids.add(item.change_id)
            decisions[item.change_id] = (approved, None if approved else "rejected in test")
        return decisions

    review_items = run.run_all(reject_first_approve_rest)

    rejected_items = [i for i in review_items if not i.approved]
    approved_items = [i for i in review_items if i.approved]
    assert len(rejected_items) >= 1
    assert len(approved_items) >= 1  # the rest were not discarded

    for item in rejected_items:
        assert item.new_html not in (run.proposal_html_after or "")
    for item in approved_items:
        assert "[AMENDED" in (run.proposal_html_after or "") or item.new_html in (run.proposal_html_after or "")


def test_full_reject_leaves_proposal_byte_identical():
    run, client = _make_run()
    run.compute_impacts()
    run.load_proposal(str(FIXTURES / "proposal_draft.html"))

    def reject_all(items):
        return {i.change_id: (False, "rejected in test") for i in items}

    run.run_all(reject_all)
    assert run.proposal_html_after == run.proposal_html_before


def test_build_log_reports_conflicts_deltas_and_untouched_proof():
    run, client = _make_run()
    run.compute_impacts()
    run.load_proposal(str(FIXTURES / "proposal_draft.html"))
    run.run_all(approve_all)

    log_text = run.build_log("FA8750-26-R-0042")
    assert "FA8750-26-R-0042" in log_text
    assert "None found" in log_text  # no conflicts in the bundled fixtures
    assert "Untouched-section proof" in log_text
    assert "SEC-VOL2-PASTPERF" in log_text
    for delta in run.deltas:
        assert delta.delta_id in log_text
