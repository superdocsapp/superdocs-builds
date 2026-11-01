from app.agents.base import DocumentContext
from app.agents.evidence_factcheck import EvidenceFactCheckAgent
from app.agents.security_pii import SecurityPIIAgent
from app.agents.structure_dependency import StructureDependencyAgent
from app.agents.style_tone import StyleToneAgent


async def test_security_pii_detects_email():
    agent = SecurityPIIAgent()
    ctx = DocumentContext(selected_text="Contact me at vishwak@example.com for details.", command="scan for pii")
    result = await agent.run(ctx)
    assert result.ok
    assert any(s.kind == "pii:email" for s in result.suggestions)


async def test_security_pii_detects_phone():
    agent = SecurityPIIAgent()
    ctx = DocumentContext(selected_text="Call the office at 415-555-0192 to confirm.", command="scan for pii")
    result = await agent.run(ctx)
    assert any(s.kind == "pii:phone" for s in result.suggestions)


async def test_security_pii_clean_text():
    agent = SecurityPIIAgent()
    ctx = DocumentContext(selected_text="This clause has no sensitive data in it.", command="scan for pii")
    result = await agent.run(ctx)
    assert result.ok
    assert result.suggestions == []


async def test_style_tone_flags_long_sentence():
    long_sentence = " ".join(["word"] * 40) + "."
    agent = StyleToneAgent()
    ctx = DocumentContext(selected_text=long_sentence, command="check style")
    result = await agent.run(ctx)
    assert any(s.kind == "style:long_sentence" for s in result.suggestions)


async def test_style_tone_flags_filler_word():
    agent = StyleToneAgent()
    ctx = DocumentContext(selected_text="This is actually a very simple clause.", command="check style")
    result = await agent.run(ctx)
    assert any(s.kind == "style:filler_word" for s in result.suggestions)


async def test_style_tone_clean_text_has_no_suggestions():
    agent = StyleToneAgent()
    ctx = DocumentContext(selected_text="The vendor delivers goods on the fifth of each month.", command="check style")
    result = await agent.run(ctx)
    assert result.suggestions == []


async def test_structure_dependency_returns_review_flag():
    agent = StructureDependencyAgent()
    ctx = DocumentContext(selected_text="Section 4 references Section 9.", command="check dependency")
    result = await agent.run(ctx)
    assert result.ok
    assert len(result.suggestions) == 1


async def test_evidence_factcheck_returns_review_flag():
    agent = EvidenceFactCheckAgent()
    ctx = DocumentContext(selected_text="Revenue grew 40% last year.", command="verify evidence")
    result = await agent.run(ctx)
    assert result.ok
    assert len(result.suggestions) == 1


def test_agent_handles_matches_trigger_keyword():
    agent = SecurityPIIAgent()
    ctx = DocumentContext(selected_text="x", command="please scan this for pii")
    assert agent.handles(ctx) is True


def test_agent_handles_rejects_unrelated_command():
    agent = SecurityPIIAgent()
    ctx = DocumentContext(selected_text="x", command="translate this paragraph")
    assert agent.handles(ctx) is False
