from redline_desk import diffing

OLD = '<p data-chunk-id="c1">Carrier liability shall not exceed $50,000 per shipment.</p>'
NEW = '<p data-chunk-id="c1">Carrier liability shall not exceed $250,000 per shipment, at full invoice value.</p>'


def test_roundtrip_word_diff():
    block = diffing.redline_block(OLD, NEW, "Redline Desk (R-101)", "2026-08-18T00:00:00Z")
    proofs = diffing.verify_roundtrip(OLD, NEW, block)
    assert proofs == {"reject_all_equals_old": True, "accept_all_equals_new": True}
    assert "<ins" in block and "<del" in block
    assert 'data-author="Redline Desk (R-101)"' in block


def test_roundtrip_preserves_untouched_words():
    block = diffing.redline_block(OLD, NEW, "A", "D")
    assert "Carrier liability shall not exceed" in diffing.reject_all(block)
    assert "$50,000" not in diffing.accept_all(block)


def test_markup_falls_back_to_whole_replace():
    old = '<p data-chunk-id="c2">Keep <b>bold</b> text.</p>'
    new = '<p data-chunk-id="c2">Changed <b>bold</b> body.</p>'
    block = diffing.redline_block(old, new, "A", "D")
    proofs = diffing.verify_roundtrip(old, new, block)
    assert proofs["reject_all_equals_old"] and proofs["accept_all_equals_new"]


def test_insertion_block():
    new = "<p>Carrier shall maintain a Satisfactory safety rating.</p>"
    block = diffing.insertion_block(new, "A", "D")
    proofs = diffing.verify_insertion(new, block)
    assert proofs["reject_all_equals_old"] and proofs["accept_all_equals_new"]


def test_identical_content_yields_no_marks():
    block = diffing.redline_block(OLD, OLD, "A", "D")
    assert "<ins" not in block and "<del" not in block


def test_reviewer_answers_are_forgiving():
    from redline_desk.cli import parse_answer

    assert parse_answer("y") == {"approved": True}
    assert parse_answer("Yes") == {"approved": True}
    assert parse_answer("n") == {"approved": False, "feedback": None}
    assert parse_answer("n keep the cap wording") == {"approved": False, "feedback": "keep the cap wording"}
    # feedback typed without a leading n is still feedback, never silently ignored
    assert parse_answer("keep the 400 daily cap but change free time to 3 hours") == {"approved": False, "feedback": "keep the 400 daily cap but change free time to 3 hours"}
    assert parse_answer("   ") is None
