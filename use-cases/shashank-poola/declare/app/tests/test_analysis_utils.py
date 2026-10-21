from schemas.declare import AnalysisProviderResponse, AnalyzeRequest
from utils.analysis import contains_evidence, supports_funding_acquisition, validate_analysis


def test_evidence_matching_is_case_insensitive_but_requires_an_exact_phrase():
    assert contains_evidence("Shashank designed the study.", "DESIGNED THE STUDY")
    assert not contains_evidence("Shashank designed the study.", "designed a study")
    assert not contains_evidence("notes", "")


def test_funding_acquisition_needs_explicit_acquisition_language():
    assert supports_funding_acquisition("Priya secured the grant.")
    assert supports_funding_acquisition("Priya led funding acquisition.")
    assert not supports_funding_acquisition("The foundation funded the work.")


def test_analysis_filters_unknown_author_and_invalid_conflict_evidence():
    request = AnalyzeRequest.model_validate({"authors": [{"id": "a", "name": "A"}], "contributions": "A built the software.", "funding": "", "conflicts": "A owns shares."})
    provider = AnalysisProviderResponse.model_validate({"contributions": [{"authorId": "outside", "evidence": "A built the software", "roleIds": ["software"], "status": "proposed"}], "conflicts": {"status": "reported", "items": [{"authorId": "a", "disclosure": "shares", "evidence": "invented"}]}})
    result = validate_analysis(request, provider)
    assert result["contributions"] == []
    assert result["conflicts"]["items"] == []
    assert {entry["type"] for entry in result["issues"]} >= {"UNKNOWN_AUTHOR", "INVALID_CONFLICT", "AMBIGUOUS_CONTRIBUTION"}
