from app import cards
from app.store import Change


def _has(card_json, text):
    return text in str(card_json)


def test_summary_card_links_draft_when_present():
    c = cards.summary_card(doc_title="Acme Renewal", doc_link="https://x/y",
                           request="draft it", produced="2 changes")
    assert c["cardsV2"][0]["cardId"] == "summary"
    assert _has(c, "Download current draft") and _has(c, "https://x/y")


def test_summary_card_omits_button_without_link():
    c = cards.summary_card(doc_title="D", doc_link=None, request="r", produced="none")
    assert not _has(c, "Download current draft")


def test_summary_card_names_reference_when_present():
    c = cards.summary_card(doc_title="2025", doc_link=None, request="r", produced="p",
                           reference="Acme 2024 Renewal")
    assert _has(c, "Referenced") and _has(c, "Acme 2024 Renewal")


def test_approval_card_has_per_item_and_bulk_buttons():
    changes = [Change("c1aaaa", "edit", "why one"), Change("c2bbbb", "delete", "why two", "approved")]
    c = cards.approval_card(session_id="s1", job_id="j1", doc_title="Doc", changes=changes)
    # Per-item controls for each change.
    assert _has(c, "✅ Approve") and _has(c, "❌ Reject")
    # Bulk shortcuts + the apply gate.
    assert _has(c, "Apply decisions") and _has(c, "Approve all") and _has(c, "Reject all")
    assert _has(c, "why one") and _has(c, "why two")
    # A decided change shows its state icon.
    assert _has(c, "✅ DELETE")
    # Buttons carry session/job/change for the CARD_CLICKED round-trip.
    assert _has(c, "s1") and _has(c, "j1") and _has(c, "c1aaaa")


def test_result_card_download_only_when_url():
    with_link = cards.result_card(doc_title="D", applied=2, rejected=0,
                                  download_url="https://x", filename="D.docx")
    assert _has(with_link, "Download D.docx")
    without = cards.result_card(doc_title="D", applied=0, rejected=2,
                                download_url=None, filename=None)
    assert not _has(without, "Download")


def test_updated_wraps_with_update_message():
    wrapped = cards.updated(cards.text("hi"))
    assert wrapped["actionResponse"]["type"] == "UPDATE_MESSAGE"
    assert wrapped["text"] == "hi"


def test_digest_card_counts():
    c = cards.digest_card(produced=[{"title": "A", "state": "1 applied, 0 rejected"}],
                          pending=[{"title": "B", "state": "2 change(s) awaiting review"}])
    assert _has(c, "Produced (1)") and _has(c, "Waiting on someone (1)")

