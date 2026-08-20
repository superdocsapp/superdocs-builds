from app.dispatch import handle_event
from app.store import Store
from tests.fakes import FakeSuperDocs

SEED = "<h1>Draft</h1>"


def _msg(text, space="spaces/AAA"):
    return {"type": "MESSAGE", "space": {"name": space}, "message": {"text": text}}


def _click(fn, session_id, job_id="job1", change_id=None, space="spaces/AAA"):
    params = [{"key": "session_id", "value": session_id}, {"key": "job_id", "value": job_id}]
    if change_id:
        params.append({"key": "change_id", "value": change_id})
    return {"type": "CARD_CLICKED", "space": {"name": space},
            "action": {"function": fn, "parameters": params}}


def _draft(fake, store, text="@app draft the renewal letter for Acme"):
    resp = handle_event(_msg(text), fake, store, seed_template=SEED)
    return resp, store.recent_session("spaces/AAA")


def test_message_drafts_and_posts_item_by_item_approval_card():
    fake, store = FakeSuperDocs(), Store()
    resp, review = _draft(fake, store)
    kinds = [c["cardId"] for c in resp["cardsV2"]]
    assert "summary" in kinds and "approval" in kinds
    # The 4-call contract begins: upload → chat_edit → poll, plus an honest draft link.
    ordered = [k[0] for k in fake.calls]
    assert ordered[:3] == ["upload", "chat_edit", "poll"]
    assert "download" in ordered  # summary card carries a real signed draft link
    # A review with the proposed changes is tracked for item-by-item decisions.
    assert review is not None and len(review.changes) == 2
    _, pending = store.digest("spaces/AAA")
    assert len(pending) == 1


def test_empty_message_asks_for_input():
    resp = handle_event(_msg("@app   "), FakeSuperDocs(), Store(), seed_template=SEED)
    assert "text" in resp


def test_digest_keyword_returns_digest_card():
    resp = handle_event(_msg("@app digest"), FakeSuperDocs(), Store(), seed_template=SEED)
    assert resp["cardsV2"][0]["cardId"] == "digest"


def test_failed_job_reports_error_after_retry():
    fake = FakeSuperDocs(fail=True)
    resp = handle_event(_msg("@app draft x"), fake, Store(), seed_template=SEED)
    assert "could not complete" in resp["text"]
    # Warmup retry: chat_edit attempted twice before giving up.
    assert sum(1 for c in fake.calls if c[0] == "chat_edit") == 2


def test_item_decision_updates_card_in_place_without_applying():
    fake, store = FakeSuperDocs(), Store()
    _, review = _draft(fake, store)
    c0 = review.changes[0].change_id
    resp = handle_event(_click("approve_one", review.session_id, review.job_id, c0),
                        fake, store, seed_template=SEED)
    # Updates the same message; does NOT approve/export yet.
    assert resp["actionResponse"]["type"] == "UPDATE_MESSAGE"
    assert resp["cardsV2"][0]["cardId"] == "approval"
    assert not any(c[0] == "approve" for c in fake.calls)
    assert store.review("spaces/AAA", review.session_id).changes[0].decision == "approved"


def test_apply_decisions_respects_per_item_choices():
    fake, store = FakeSuperDocs(), Store()
    _, review = _draft(fake, store)
    a, b = review.changes[0].change_id, review.changes[1].change_id
    handle_event(_click("approve_one", review.session_id, review.job_id, a), fake, store, seed_template=SEED)
    handle_event(_click("reject_one", review.session_id, review.job_id, b), fake, store, seed_template=SEED)
    resp = handle_event(_click("apply_decisions", review.session_id, review.job_id),
                        fake, store, seed_template=SEED)
    assert resp["cardsV2"][0]["cardId"] == "result"
    approve = next(c for c in fake.calls if c[0] == "approve")
    decisions = {d["change_id"]: d["approved"] for d in approve[3]}
    assert decisions[a] is True and decisions[b] is False
    produced, pending = store.digest("spaces/AAA")
    assert produced[0]["state"] == "1 applied, 1 rejected" and not pending


def test_reject_all_does_not_download():
    fake, store = FakeSuperDocs(), Store()
    _, review = _draft(fake, store)
    fake.calls.clear()
    handle_event(_click("reject_all", review.session_id, review.job_id), fake, store, seed_template=SEED)
    assert any(c[0] == "approve" for c in fake.calls)
    assert not any(c[0] == "download" for c in fake.calls)  # nothing applied → no export link


def test_approve_all_applies_and_links_download():
    fake, store = FakeSuperDocs(), Store()
    _, review = _draft(fake, store)
    resp = handle_event(_click("approve_all", review.session_id, review.job_id), fake, store, seed_template=SEED)
    assert resp["cardsV2"][0]["cardId"] == "result"
    assert any(c[0] == "download" for c in fake.calls)


def test_using_last_years_reuses_session_no_reupload():
    # "revise it" is a follow-up → edit the same doc by reusing its session.
    fake, store = FakeSuperDocs(), Store()
    _, first = _draft(fake, store)
    uploads_before = sum(1 for c in fake.calls if c[0] == "upload")
    handle_event(_msg("@app revise it to be shorter"), fake, store, seed_template=SEED)
    uploads_after = sum(1 for c in fake.calls if c[0] == "upload")
    assert uploads_after == uploads_before  # continuity: no fresh seed upload
    assert store.recent_session("spaces/AAA").session_id == first.session_id


def test_reference_opens_prior_doc_as_reference_tab():
    # "using last year's" → open the prior produced doc as a tab, draft a NEW doc.
    fake, store = FakeSuperDocs(), Store()
    _, first = _draft(fake, store)
    # Apply so the prior doc gets a durable File id it can be referenced by.
    handle_event(_click("approve_all", first.session_id, first.job_id), fake, store, seed_template=SEED)
    fake.calls.clear()
    resp = handle_event(_msg("@app draft the 2025 renewal using last year's letter"),
                        fake, store, seed_template=SEED)
    opened = [c for c in fake.calls if c[0] == "open_docs"]
    assert opened and opened[0][2] == (f"dur-{first.session_id}",)  # prior durable id opened as tab
    assert not any(c[0] == "upload" for c in fake.calls)  # referenced, not re-seeded
    assert "Referenced" in str(resp)  # summary card names the source


def test_no_changes_reports_ready_with_download():
    fake, store = FakeSuperDocs(changes=[]), Store()
    resp, _ = _draft(fake, store)
    assert resp["cardsV2"][0]["cardId"] == "summary"
    assert any(c[0] == "download" for c in fake.calls)  # ready doc is downloadable
    produced, pending = store.digest("spaces/AAA")
    assert produced[0]["state"] == "ready — nothing to review" and not pending


def test_expired_review_click_is_handled():
    resp = handle_event(_click("approve_all", "unknown-session"), FakeSuperDocs(), Store(),
                        seed_template=SEED)
    assert resp["actionResponse"]["type"] == "UPDATE_MESSAGE"
    assert "expired" in resp["text"]


def test_added_to_space_greets():
    resp = handle_event({"type": "ADDED_TO_SPACE", "space": {"name": "spaces/AAA"}},
                        FakeSuperDocs(), Store(), seed_template=SEED)
    assert "text" in resp

