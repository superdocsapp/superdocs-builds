from src.outline_agent import create_paper_with_outline, FIXED_SECTION_TITLES
from src.mcp_client import FakeMCPClient


def test_outline_creates_session_and_document_with_all_sections():
    client = FakeMCPClient()
    paper = create_paper_with_outline("Retrieval-augmented generation in legal QA", client)

    assert paper.session_id is not None
    assert len(paper.sections) == len(FIXED_SECTION_TITLES)
    assert [s.title for s in paper.sections] == FIXED_SECTION_TITLES
    assert [s.order for s in paper.sections] == list(range(1, len(FIXED_SECTION_TITLES) + 1))

    ids = [s.id for s in paper.sections]
    assert len(ids) == len(set(ids))

    assert len(client.calls) == 1
    call_name, args = client.calls[0]
    assert call_name == "create_session_with_document"
    assert args["session_id"] == paper.session_id

    for title in FIXED_SECTION_TITLES:
        assert title in args["initial_html"]