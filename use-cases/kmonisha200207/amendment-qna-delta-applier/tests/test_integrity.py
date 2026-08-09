from delta_applier.integrity import verify_untouched

BEFORE = (
    '<div data-section-id="A"><p>Alpha content unchanged.</p></div>'
    '<div data-section-id="B"><p>Beta content, will change.</p></div>'
)
AFTER = (
    '<div data-section-id="A"><p>Alpha content unchanged.</p></div>'
    '<div data-section-id="B"><p>Beta content, HAS changed.</p></div>'
)


def test_untouched_section_hash_matches():
    proofs = verify_untouched(BEFORE, AFTER, ["A"])
    assert proofs["A"].verified_untouched is True


def test_changed_section_hash_does_not_match():
    proofs = verify_untouched(BEFORE, AFTER, ["B"])
    assert proofs["B"].verified_untouched is False


def test_missing_section_fails_rather_than_silently_passing():
    proofs = verify_untouched(BEFORE, AFTER, ["DOES-NOT-EXIST"])
    assert proofs["DOES-NOT-EXIST"].verified_untouched is False
    assert proofs["DOES-NOT-EXIST"].before_hash is None
