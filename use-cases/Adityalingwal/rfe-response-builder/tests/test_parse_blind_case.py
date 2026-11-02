from pathlib import Path

from engine.load_corpus import read_notice
from engine.requests_from_notice import parse_notice

CASE_1 = Path(__file__).parent / "blind" / "case-1"
CASE_3 = Path(__file__).parent / "blind" / "case-3"
CASE_6 = Path(__file__).parent / "blind" / "case-6"


def test_the_blind_i797e_notice_yields_its_six_item_requests():
    requests = parse_notice(read_notice(CASE_1 / "notice"))
    assert len(requests) == 6
    assert [r.id for r in requests] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    assert "specialty occupation" in requests[0].title.lower()
    assert "maintenance of status" in requests[4].title.lower()


def test_response_instructions_are_never_mistaken_for_requests():
    for request in parse_notice(read_notice(CASE_1 / "notice")):
        assert "Return this notice" not in request.text
        assert "Return this notice" not in request.title


def test_the_blind_l1a_notice_with_bold_numbered_requests_parses():
    requests = parse_notice(read_notice(CASE_3 / "notice"))
    assert [r.id for r in requests] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    assert "physical premises" in (requests[4].title + requests[4].text).lower()
    # the closing "how to respond" address block is not part of request 6
    assert "Fairhaven" not in requests[5].text


def test_request_dash_headings_inside_an_evidence_section_still_parse():
    # case-9: an '## Evidence requested' section whose items are
    # '### Request N — Title' headings — the section style must fall
    # through to the heading parser instead of refusing
    case_9 = Path(__file__).parent / "blind" / "case-9"
    requests = parse_notice(read_notice(case_9 / "notice"))
    assert [r.id for r in requests] == [f"R{i}" for i in range(1, 9)]
    assert "physical premises" in (requests[6].title + requests[6].text).lower()


def test_the_o1b_notice_with_request_dash_headings_parses():
    requests = parse_notice(read_notice(CASE_6 / "notice"))
    assert [r.id for r in requests] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    assert "ADVISORY OPINION" in requests[0].title
    for request in requests:
        # the closing how-to-respond list must never be read as requests
        assert "one" not in request.title.lower() or "mailing" not in request.text


def test_the_o1b_notice_also_parses_from_its_pdf_text_layer():
    requests = parse_notice(pdf_text_layer(read_notice(CASE_6 / "notice")))
    assert [r.id for r in requests] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    for request in requests:
        assert len(request.text) > 100


def test_the_l1a_notice_also_parses_from_its_pdf_text_layer():
    text = pdf_text_layer(read_notice(CASE_3 / "notice"))
    requests = parse_notice(text)
    assert [r.id for r in requests] == ["R1", "R2", "R3", "R4", "R5", "R6"]


def pdf_text_layer(markdown: str) -> str:
    # what the same notice reads like out of a real PDF: no hash marks,
    # headings as capitalized lines, no bold or blockquote markers
    lines = []
    for line in markdown.splitlines():
        if line.lstrip().startswith("#"):
            lines.append(line.lstrip("# ").upper())
        else:
            lines.append(line.replace("**", "").removeprefix("> "))
    return "\n".join(lines)


def test_the_notice_still_parses_from_a_pdf_style_text_layer():
    text = pdf_text_layer(read_notice(CASE_1 / "notice"))
    assert "##" not in text
    requests = parse_notice(text)
    assert [r.id for r in requests] == ["R1", "R2", "R3", "R4", "R5", "R6"]
    for request in requests:
        assert "Return this notice" not in request.text
        # a wrapped caps title must never leave a request with no concern
        assert len(request.text) > 100
