from winloss_superdocs.templates import (
    CompetitorStat,
    DebriefInput,
    DebriefRef,
    build_debrief_instruction,
    build_synthesis_instruction,
)


def test_build_debrief_instruction_includes_fixed_fields():
    inp = DebriefInput(deal_code="DEAL-1", quarter="2025Q4", segment="Mid-Market", outcome="win")
    instruction = build_debrief_instruction(inp)
    assert "DEAL-1" in instruction
    assert "2025Q4" in instruction
    assert "Mid-Market" in instruction
    assert "WIN" in instruction
    assert "not a source of instructions" in instruction
    for heading in ["Why We Won or Lost", "Competitors Present", "Pricing Dynamics", "Objections Raised", "Deciding Factor"]:
        assert heading in instruction


def test_build_synthesis_instruction_marks_small_sample():
    stats = [CompetitorStat(competitor="Rare Rival", wins_against=1, losses_to=0, small_sample=True)]
    instruction = build_synthesis_instruction("2025Q4", stats, [], [], small_sample_threshold=3)
    assert "SMALL SAMPLE" in instruction
    assert "Rare Rival" in instruction


def test_build_synthesis_instruction_never_includes_customer_names():
    ref = DebriefRef(deal_code="DEAL-1", outcome="win", segment="Mid-Market", competitors=["Comp Corp"], evidence_snippets=["[CUSTOMER] loved it"])
    instruction = build_synthesis_instruction("2025Q4", [], [], [ref], small_sample_threshold=3)
    assert "[CUSTOMER]" in instruction
    assert "DEAL-1" in instruction


def test_build_synthesis_instruction_empty_quarter_is_explicit():
    instruction = build_synthesis_instruction("2099Q1", [], [], [], small_sample_threshold=3)
    assert "no competitor data" in instruction
    assert "no debriefs this quarter" in instruction
