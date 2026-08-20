from pathlib import Path

import pytest

from rfe_response_builder.rfe import (
    EvidenceStatus,
    NewEvidenceCatalog,
    NewEvidenceEntry,
    PetitionArgument,
    PriorPetition,
    RFERequest,
    all_requests_answered,
    arguments_from_free_text,
    build_coverage_checklist,
    build_exhibit_list,
    build_response_instruction,
    classify_evidence_status,
    is_substantive_reply,
    new_evidence_note_from_entries,
    parse_rfe_notice,
    response_section_heading,
    sanitize_case_id,
)

SAMPLE_NOTICE = (Path(__file__).parent.parent / "data" / "sample_rfe_notice.txt").read_text()


def test_parse_rfe_notice_splits_into_three_issues():
    reqs = parse_rfe_notice(SAMPLE_NOTICE)
    assert len(reqs) == 3
    assert [r.request_id for r in reqs] == ["1", "2", "3"]
    assert "bona fide" in reqs[0].text
    assert "translation" in reqs[1].text
    assert "poverty guidelines" in reqs[2].text


def test_parse_rfe_notice_no_markers_falls_back_to_single_request():
    text = "The officer needs more evidence about the marriage. No numbered list here."
    reqs = parse_rfe_notice(text)
    assert len(reqs) == 1
    assert reqs[0].request_id == "1"
    assert reqs[0].text == text


def test_parse_rfe_notice_empty_text_returns_no_requests():
    assert parse_rfe_notice("") == []
    assert parse_rfe_notice("   \n  ") == []


def test_parse_rfe_notice_never_drops_content_between_markers():
    reqs = parse_rfe_notice(SAMPLE_NOTICE)
    total_len = sum(len(r.text) for r in reqs)
    # sanity: the parsed bodies should carry the bulk of the notice content
    assert total_len > 300


def test_best_match_finds_relevant_prior_argument():
    petition = PriorPetition(arguments=[
        PetitionArgument("bona_fide_relationship", "joint bank statements showing shared household expenses", "p.3"),
        PetitionArgument("marriage_certificate", "civil marriage certificate from local registrar", "Exhibit C"),
    ])
    req = RFERequest("1", "The record lacks sufficient evidence of a bona fide marital relationship, joint household expenses.")
    match = petition.best_match(req)
    assert match is not None
    assert match.topic_id == "bona_fide_relationship"


def test_best_match_returns_none_when_no_overlap():
    petition = PriorPetition(arguments=[
        PetitionArgument("unrelated_topic", "completely different subject matter entirely", "p.9"),
    ])
    req = RFERequest("1", "Provide certified translation of marriage certificate documentation.")
    assert petition.best_match(req) is None


def test_build_response_instruction_with_prior_match_forbids_restating():
    req = RFERequest("1", "Provide more evidence of bona fide relationship.")
    prior = PetitionArgument("bona_fide_relationship", "joint bank statements", "p.3")
    instruction = build_response_instruction(req, prior)
    assert "p.3" in instruction
    assert "Do not simply restate" in instruction
    assert "joint bank statements" in instruction


def test_build_response_instruction_without_prior_match_says_so_explicitly():
    req = RFERequest("2", "Provide something the petition never covered.")
    instruction = build_response_instruction(req, None)
    assert "did not clearly address this point" in instruction
    assert "rather than inventing" in instruction


def test_build_response_instruction_includes_new_evidence_note():
    req = RFERequest("1", "x")
    instruction = build_response_instruction(req, None, new_evidence_note="joint lease agreement")
    assert "joint lease agreement" in instruction


def test_coverage_checklist_flags_unanswered_items():
    reqs = [RFERequest("1", "a"), RFERequest("2", "b"), RFERequest("3", "c")]
    matches = {"1": None, "2": None, "3": None}
    rows = build_coverage_checklist(reqs, matches, answered_ids={"1", "3"})
    assert not all_requests_answered(rows)
    unanswered = [r for r in rows if not r.answered]
    assert len(unanswered) == 1
    assert unanswered[0].request_id == "2"


def test_coverage_checklist_all_answered_true_when_complete():
    reqs = [RFERequest("1", "a"), RFERequest("2", "b")]
    matches = {"1": None, "2": None}
    rows = build_coverage_checklist(reqs, matches, answered_ids={"1", "2"})
    assert all_requests_answered(rows)


def test_coverage_checklist_carries_matched_source_ref():
    reqs = [RFERequest("1", "a")]
    match = PetitionArgument("t", "text", "Exhibit C")
    rows = build_coverage_checklist(reqs, {"1": match}, answered_ids={"1"})
    assert rows[0].matched_prior_argument == "Exhibit C"


# --- top-N prior-petition matching -------------------------------------------

def test_best_matches_returns_multiple_ranked_matches():
    petition = PriorPetition(arguments=[
        PetitionArgument("a", "joint bank statements shared household expenses commingle", "p.1"),
        PetitionArgument("b", "joint household lease shared expenses documentation", "p.2"),
        PetitionArgument("c", "completely unrelated employment salary letter", "p.3"),
    ])
    req = RFERequest("1", "record lacks evidence of shared household expenses commingle documentation")
    matches = petition.best_matches(req, top_n=2)
    assert len(matches) == 2
    assert matches[0].topic_id in {"a", "b"}
    assert matches[1].topic_id in {"a", "b"}
    # best_match() stays a thin wrapper returning only the top result
    assert petition.best_match(req) == matches[0]


def test_best_matches_respects_top_n_limit():
    petition = PriorPetition(arguments=[
        PetitionArgument("a", "marriage relationship household evidence", "p.1"),
        PetitionArgument("b", "marriage relationship household documentation", "p.2"),
        PetitionArgument("c", "marriage relationship household support", "p.3"),
    ])
    req = RFERequest("1", "marriage relationship household evidence documentation support")
    assert len(petition.best_matches(req, top_n=1)) == 1
    assert len(petition.best_matches(req, top_n=10)) == 3


# --- new evidence identification ---------------------------------------------

def test_new_evidence_catalog_matches_relevant_entry():
    catalog = NewEvidenceCatalog(entries=[
        NewEvidenceEntry("translation", "certified English translation of marriage certificate", "Certified Translation"),
        NewEvidenceEntry("tax", "federal tax return showing income poverty guidelines", "Federal Tax Return"),
    ])
    req = RFERequest("2", "Provide a certified translation of the marriage certificate document.")
    matches = catalog.best_matches(req)
    assert len(matches) == 1
    assert matches[0].topic_id == "translation"


def test_new_evidence_catalog_returns_empty_when_no_overlap():
    catalog = NewEvidenceCatalog(entries=[
        NewEvidenceEntry("translation", "certified English translation of marriage certificate", "Certified Translation"),
    ])
    req = RFERequest("1", "totally unconnected request about zoning permits")
    assert catalog.best_matches(req) == []


def test_new_evidence_note_from_entries_joins_descriptions():
    entries = [
        NewEvidenceEntry("a", "joint lease agreement", "Lease"),
        NewEvidenceEntry("b", "third party affidavits", "Affidavits"),
    ]
    note = new_evidence_note_from_entries(entries)
    assert "joint lease agreement" in note
    assert "third party affidavits" in note


def test_new_evidence_note_from_entries_returns_none_when_empty():
    assert new_evidence_note_from_entries([]) is None


# --- exhibit assembly ----------------------------------------------------------

def test_build_exhibit_list_numbers_sequentially_in_notice_order():
    reqs = [RFERequest("1", "a"), RFERequest("2", "b")]
    e1 = NewEvidenceEntry("t1", "desc one", "Label One")
    e2 = NewEvidenceEntry("t2", "desc two", "Label Two")
    exhibits = build_exhibit_list(reqs, {"1": [e1], "2": [e2]})
    assert [ex.number for ex in exhibits] == [1, 2]
    assert exhibits[0].label == "Label One"
    assert exhibits[1].label == "Label Two"


def test_build_exhibit_list_dedupes_evidence_shared_across_requests():
    reqs = [RFERequest("1", "a"), RFERequest("2", "b")]
    shared = NewEvidenceEntry("shared", "evidence supporting both items", "Shared Exhibit")
    exhibits = build_exhibit_list(reqs, {"1": [shared], "2": [shared]})
    assert len(exhibits) == 1
    assert set(exhibits[0].request_ids) == {"1", "2"}


def test_build_exhibit_list_empty_when_no_evidence_matched():
    reqs = [RFERequest("1", "a")]
    assert build_exhibit_list(reqs, {}) == []


# --- coverage checklist with evidence + exhibits --------------------------------

def test_coverage_checklist_includes_new_evidence_and_exhibit_numbers():
    reqs = [RFERequest("1", "a")]
    entry = NewEvidenceEntry("t", "some new evidence description", "Some Label")
    evidence_matches = {"1": [entry]}
    exhibits = build_exhibit_list(reqs, evidence_matches)
    rows = build_coverage_checklist(
        reqs, {"1": None}, answered_ids={"1"},
        evidence_matches=evidence_matches, exhibits=exhibits,
    )
    assert rows[0].new_evidence == ["some new evidence description"]
    assert rows[0].exhibit_numbers == [1]


def test_coverage_checklist_accepts_list_of_prior_arguments():
    reqs = [RFERequest("1", "a")]
    matches = [PetitionArgument("t1", "x", "p.1"), PetitionArgument("t2", "y", "p.2")]
    rows = build_coverage_checklist(reqs, {"1": matches}, answered_ids={"1"})
    assert rows[0].matched_prior_arguments == ["p.1", "p.2"]
    assert rows[0].matched_prior_argument == "p.1"


# --- filename sanitization ------------------------------------------------------

def test_sanitize_case_id_passes_through_clean_id():
    assert sanitize_case_id("CASE-2002") == "CASE-2002"


def test_sanitize_case_id_strips_path_traversal_and_slashes():
    assert sanitize_case_id("../../etc/passwd") == "etc-passwd"
    assert "/" not in sanitize_case_id("a/b/c")
    assert ".." not in sanitize_case_id("../CASE-1")


def test_sanitize_case_id_raises_on_no_usable_characters():
    with pytest.raises(ValueError):
        sanitize_case_id("///")


# --- answer-quality gate (is_substantive_reply) ----------------------------------

def test_substantive_reply_accepted():
    text = "The record establishes that the marriage is bona fide based on joint financial records."
    assert is_substantive_reply(text)


def test_refusal_reply_rejected():
    assert not is_substantive_reply("I don't have enough information to address this request.")


def test_empty_reply_rejected():
    assert not is_substantive_reply("")
    assert not is_substantive_reply(None)
    assert not is_substantive_reply("   ")


def test_too_short_reply_rejected():
    assert not is_substantive_reply("Okay, done.")


def test_apology_reply_rejected():
    assert not is_substantive_reply("Sorry, I cannot complete this request without more context.")


# --- evidence status classification ----------------------------------------------

def test_evidence_status_already_submitted_when_prior_match():
    prior = [PetitionArgument("t1", "x", "p.1")]
    assert classify_evidence_status(prior, []) == EvidenceStatus.ALREADY_SUBMITTED


def test_evidence_status_new_evidence_when_only_catalog_match():
    evidence = [NewEvidenceEntry("t1", "desc", "Exhibit Label")]
    assert classify_evidence_status([], evidence) == EvidenceStatus.NEW_EVIDENCE_IDENTIFIED


def test_evidence_status_needs_review_when_no_match_at_all():
    assert classify_evidence_status([], []) == EvidenceStatus.NEEDS_ATTORNEY_REVIEW


# --- multi-document ingestion (arguments_from_free_text) -------------------------

def test_arguments_from_free_text_splits_paragraphs_with_traceable_refs():
    text = (
        "This is the first paragraph and it is long enough to count as an argument.\n\n"
        "This is the second paragraph, also long enough to be picked up by the parser.\n\n"
        "short"
    )
    args = arguments_from_free_text("employer_letter.txt", text)
    assert len(args) == 2  # the short fragment is dropped
    assert args[0].source_ref == "employer_letter.txt, \u00b61"
    assert args[1].source_ref == "employer_letter.txt, \u00b62"
    assert "first paragraph" in args[0].text


def test_arguments_from_free_text_empty_input_returns_nothing():
    assert arguments_from_free_text("doc.txt", "") == []


# --- response section mapping -----------------------------------------------------

def test_coverage_checklist_maps_answered_item_to_response_section():
    reqs = [RFERequest("1", "a")]
    rows = build_coverage_checklist(reqs, {"1": None}, answered_ids={"1"})
    assert rows[0].response_section == "Response to Item 1"


def test_coverage_checklist_unanswered_item_has_no_response_section():
    reqs = [RFERequest("1", "a")]
    rows = build_coverage_checklist(reqs, {"1": None}, answered_ids=set())
    assert rows[0].response_section == "(not answered)"


def test_response_instruction_titles_section_to_match_checklist():
    r = RFERequest("2", "some concern")
    instruction = build_response_instruction(r, None)
    assert response_section_heading("2") in instruction


# --- fuzzy/stemmed matching -------------------------------------------------

def test_fuzzy_matches_catches_morphological_variant_keyword_matching_misses():
    petition = PriorPetition(arguments=[
        PetitionArgument("t1", "Extensive specialized professional experience is documented in this technical field.",
                          "Petition Letter, p. 3"),
    ])
    # "specialized" vs "specializing" -- different exact tokens, same stem.
    req = RFERequest("1", "The record does not clearly show that applicant is specializing in this occupation.")
    assert petition.best_matches(req) == []  # strict matcher correctly finds nothing
    fuzzy = petition.fuzzy_matches(req)
    assert len(fuzzy) == 1
    assert fuzzy[0][0].source_ref == "Petition Letter, p. 3"
    assert 0 < fuzzy[0][1] <= 1


def test_fuzzy_matches_returns_nothing_when_no_stem_overlap():
    petition = PriorPetition(arguments=[
        PetitionArgument("t1", "Completely unrelated content about kitchen appliances.", "p. 9"),
    ])
    req = RFERequest("1", "The beneficiary's specialized technical expertise in aerospace engineering.")
    assert petition.fuzzy_matches(req) == []


def test_plan_response_only_computes_fuzzy_suggestions_when_strict_match_empty():
    from rfe_response_builder.generate import plan_response
    notice = "1. The record does not clearly show that applicant is specializing in the occupation.\n"
    petition = PriorPetition(arguments=[
        PetitionArgument("t1", "Extensive specialized professional experience is documented in this technical field.", "p. 1"),
    ])
    _, petition_matches, _, _, fuzzy = plan_response(notice, petition, NewEvidenceCatalog())
    assert petition_matches["1"] == []
    assert len(fuzzy["1"]) == 1
