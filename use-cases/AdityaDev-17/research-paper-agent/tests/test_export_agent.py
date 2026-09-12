from src.models import Paper, Section, SectionStatus, PaperStatus
from src.mcp_client import FakeMCPClient
from src.export_agent import export_paper


def test_export_blocks_when_a_section_is_unverified():
    paper = Paper(id="p1", topic="test", session_id="sess-1")
    s1 = Section(id="s1", paper_id="p1", title="Intro", order=1)
    s1.status = SectionStatus.VERIFIED
    s2 = Section(id="s2", paper_id="p1", title="Method", order=2)
    s2.status = SectionStatus.FLAGGED  # not yet fixed
    paper.sections = [s1, s2]

    client = FakeMCPClient()
    try:
        export_paper(paper, client)
        assert False, "Expected export to be blocked"
    except ValueError as e:
        assert "Method" in str(e)

    # And critically: export_document must NOT have been called
    assert client.calls == []


def test_export_succeeds_when_all_sections_verified():
    paper = Paper(id="p1", topic="test", session_id="sess-1")
    s1 = Section(id="s1", paper_id="p1", title="Intro", order=1)
    s1.status = SectionStatus.VERIFIED
    paper.sections = [s1]

    client = FakeMCPClient()
    path = export_paper(paper, client)

    assert path == "/exports/sess-1.docx"
    assert paper.status == PaperStatus.EXPORTED

    assert len(client.calls) == 1
    call_name, args = client.calls[0]
    assert call_name == "export_document"
    assert args["session_id"] == "sess-1"