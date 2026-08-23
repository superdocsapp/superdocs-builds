from app.workflow.near_duplicate import NearDuplicateDetector, jaccard_similarity

CONTRACT_A = """SERVICES AGREEMENT
Counterparty: Acme Logistics Inc
Effective Date: 2026-01-15
Expiration Date: 2027-01-14
Value: $84,000
This agreement covers logistics management services provided on an ongoing basis
throughout the term with quarterly review checkpoints and standard termination clauses.
"""

CONTRACT_A_TRIVIAL_EDIT = CONTRACT_A.replace("2026-01-15", "2026-01-16")

CONTRACT_B_UNRELATED = """INVOICE
Amount Due: $500
Bill To: Totally Different Company
This is a completely unrelated one-time invoice for consulting services rendered
in a single engagement with no relation whatsoever to any other document.
"""


def test_identical_text_has_similarity_one():
    assert jaccard_similarity(CONTRACT_A, CONTRACT_A) == 1.0


def test_completely_different_text_has_low_similarity():
    assert jaccard_similarity(CONTRACT_A, CONTRACT_B_UNRELATED) < 0.1


def test_trivial_edit_still_scores_highly_similar():
    similarity = jaccard_similarity(CONTRACT_A, CONTRACT_A_TRIVIAL_EDIT)
    assert similarity > 0.85


def test_both_empty_is_trivially_identical():
    assert jaccard_similarity("", "") == 1.0


def test_one_empty_one_not_is_zero_similarity():
    assert jaccard_similarity("", CONTRACT_A) == 0.0


def test_similarity_is_symmetric():
    assert jaccard_similarity(CONTRACT_A, CONTRACT_B_UNRELATED) == jaccard_similarity(
        CONTRACT_B_UNRELATED, CONTRACT_A
    )


# --- detector ------------------------------------------------------------


def test_first_document_registered_has_no_match():
    detector = NearDuplicateDetector()
    match = detector.check_and_register("f1", CONTRACT_A)
    assert match is None


def test_near_duplicate_of_a_different_file_id_is_detected():
    detector = NearDuplicateDetector()
    detector.check_and_register("f1", CONTRACT_A)
    match = detector.check_and_register("f2", CONTRACT_A_TRIVIAL_EDIT)
    assert match is not None
    assert match.file_id == "f1"
    assert match.similarity > 0.85


def test_unrelated_document_is_not_flagged():
    detector = NearDuplicateDetector()
    detector.check_and_register("f1", CONTRACT_A)
    match = detector.check_and_register("f2", CONTRACT_B_UNRELATED)
    assert match is None


def test_reprocessing_the_same_file_id_is_never_flagged_against_itself():
    detector = NearDuplicateDetector()
    detector.check_and_register("f1", CONTRACT_A)
    match = detector.check_and_register("f1", CONTRACT_A_TRIVIAL_EDIT)  # same file_id, version bump
    assert match is None


def test_returns_the_best_match_when_multiple_similar_files_exist():
    detector = NearDuplicateDetector()
    detector.check_and_register("f1", CONTRACT_A)
    detector.check_and_register("f2", CONTRACT_A_TRIVIAL_EDIT)
    match = detector.check_and_register("f3", CONTRACT_A)  # identical to f1, near-identical to f2
    assert match is not None
    assert match.file_id == "f1"
    assert match.similarity == 1.0


def test_threshold_is_configurable():
    strict_detector = NearDuplicateDetector(similarity_threshold=0.99)
    strict_detector.check_and_register("f1", CONTRACT_A)
    match = strict_detector.check_and_register("f2", CONTRACT_A_TRIVIAL_EDIT)
    assert match is None  # trivial edit's ~0.9 similarity doesn't clear a 0.99 bar
