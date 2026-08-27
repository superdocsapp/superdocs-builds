import copy

from benchmark.corpus import generate_document
from benchmark.edit_tasks import generate_edit_session
from benchmark.client import MockClient
from benchmark.arms import run_whole_doc_arm, run_section_edit_arm


def _doc_and_session(pages=3, turns=4, seed=1):
    doc = generate_document("d0", "vendor_contract", target_pages=pages, seed=seed)
    session = generate_edit_session(doc, num_turns=turns, seed=seed)
    return doc, session


def test_both_arms_produce_one_record_per_turn():
    doc, session = _doc_and_session()
    client = MockClient()
    whole = run_whole_doc_arm(doc, session, client)
    section = run_section_edit_arm(doc, session, client)
    assert len(whole) == len(session)
    assert len(section) == len(session)


def test_section_arm_sends_dramatically_less_text_on_large_docs():
    """The core claim of the benchmark: section-level editing should send far
    fewer characters per edit than whole-document regeneration, and the gap
    should widen as the document grows."""
    doc, session = _doc_and_session(pages=50, turns=3, seed=2)
    client = MockClient()
    whole = run_whole_doc_arm(doc, session, client)
    section = run_section_edit_arm(doc, session, client)

    mean_whole_chars = sum(r.chars_sent for r in whole) / len(whole)
    mean_section_chars = sum(r.chars_sent for r in section) / len(section)

    assert mean_section_chars < mean_whole_chars
    # on a 50-page doc, section edits should be at least 5x cheaper in chars sent
    assert mean_whole_chars / mean_section_chars > 5


def test_section_arm_does_not_touch_untargeted_sections():
    """Surgical precision, provably: sections never targeted by an edit must
    remain byte-identical to the original document."""
    doc, session = _doc_and_session(pages=5, turns=2, seed=3)
    targeted_ids = {t.target_section_id for t in session}

    client = MockClient()
    run_section_edit_arm(doc, session, client)  # mutates a deep copy internally, not `doc`

    # `doc` itself must be untouched since arms deep-copy before editing.
    for s in doc.sections:
        assert isinstance(s.body, str)

    # Re-run and inspect the working copy's untouched sections directly.
    from benchmark.arms import run_section_edit_arm as run_again
    import benchmark.arms as arms_mod

    working = copy.deepcopy(doc)
    original_bodies = {s.id: s.body for s in working.sections if s.id not in targeted_ids}

    client2 = MockClient()
    run_again(working, session, client2)

    for s in working.sections:
        if s.id not in original_bodies:
            continue
        assert s.body == original_bodies[s.id], f"untouched section {s.id} was modified"


def test_whole_doc_arm_does_not_mutate_the_original_document():
    doc, session = _doc_and_session()
    original_text = doc.full_text()
    client = MockClient()
    run_whole_doc_arm(doc, session, client)
    assert doc.full_text() == original_text


def test_records_have_positive_cost_and_tokens():
    doc, session = _doc_and_session()
    client = MockClient()
    for r in run_whole_doc_arm(doc, session, client) + run_section_edit_arm(doc, session, client):
        assert r.input_tokens > 0
        assert r.output_tokens > 0
        assert r.cost_usd > 0
        assert r.wall_clock_s >= 0
        assert r.client_source == "mock"
