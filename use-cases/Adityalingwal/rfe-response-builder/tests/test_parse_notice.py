import pytest

from engine.requests_from_notice import parse_notice


def test_notice_splits_into_five_requests_with_source_numbering(notice_text):
    requests = parse_notice(notice_text)
    assert [r.id for r in requests] == ["R1", "R2", "R3", "R4", "R5"]
    assert requests[0].title == "Beneficiary's educational qualifications"
    assert requests[4].title == "Beneficiary's maintenance of status"


def test_no_request_is_invented_every_word_comes_from_the_notice(notice_text):
    for request in parse_notice(notice_text):
        assert request.title in notice_text
        assert request.text in notice_text


def test_a_petition_document_is_refused_as_a_notice_with_a_named_fix(petition):
    some_petition_doc = next(iter(petition.values()))
    with pytest.raises(
        ValueError, match="Could not find the officer's requests"
    ) as refusal:
        parse_notice(some_petition_doc)
    assert "What to do: open the notice" in str(refusal.value)


def test_a_notice_without_numbered_requests_is_refused_naming_the_file_it_read():
    empty_section = "# Notice\n\n## Evidence requested\n\nSend more evidence.\n"
    with pytest.raises(
        ValueError, match="Could not find the officer's requests"
    ) as refusal:
        parse_notice(empty_section, source_name="rfe-notice.pdf")
    message = str(refusal.value)
    assert "rfe-notice.pdf" in message
    assert "ITEM 1 — Evidence that ..." in message
