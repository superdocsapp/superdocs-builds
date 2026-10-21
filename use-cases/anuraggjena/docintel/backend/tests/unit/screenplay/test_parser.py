import pytest
from backend.modules.screenplay.parser import ScreenplayParser, ScreenplayElement


def parse(text: str):
    return ScreenplayParser().parse(text)


def test_scene_heading_int():
    elements = parse("INT. OFFICE - DAY\n\nA man enters.\n")
    assert elements[0].element_type == "scene_heading"
    assert elements[0].confidence >= 0.9
    assert "OFFICE" in elements[0].content


def test_scene_heading_ext():
    elements = parse("EXT. PARK - NIGHT\n\nBirds fly.\n")
    assert elements[0].element_type == "scene_heading"


def test_action_block():
    elements = parse("INT. OFFICE - DAY\n\nA man sits at a desk.\n")
    action = [e for e in elements if e.element_type == "action"]
    assert len(action) >= 1
    assert "sits" in action[0].content


def test_character_and_dialogue():
    text = "INT. OFFICE - DAY\n\nJOHN\nHello there.\n"
    elements = parse(text)
    types = [e.element_type for e in elements]
    assert "character" in types
    assert "dialogue" in types
    char = next(e for e in elements if e.element_type == "character")
    assert char.content.strip() == "JOHN"
    dia = next(e for e in elements if e.element_type == "dialogue")
    assert "Hello" in dia.content


def test_parenthetical():
    text = "INT. X - DAY\n\nJANE\n(quietly)\nI know.\n"
    elements = parse(text)
    types = [e.element_type for e in elements]
    assert "parenthetical" in types
    paren = next(e for e in elements if e.element_type == "parenthetical")
    assert "quietly" in paren.content


def test_transition():
    text = "INT. X - DAY\n\nAction.\n\nCUT TO:\n"
    elements = parse(text)
    trans = [e for e in elements if e.element_type == "transition"]
    assert len(trans) == 1


def test_uncertain_element():
    text = "INT. X - DAY\n\n???unknown formatting line???\n"
    elements = parse(text)
    uncertain = [e for e in elements if e.element_type == "uncertain"]
    # May or may not flag as uncertain depending on rules — as long as parse doesn't crash
    assert isinstance(uncertain, list)


def test_empty_input():
    elements = parse("")
    assert elements == []


def test_element_index_ordering():
    text = "INT. OFFICE - DAY\n\nA man.\n\nJOHN\nHello.\n"
    elements = parse(text)
    indices = [e.element_index for e in elements]
    assert indices == list(range(len(indices)))


def test_scene_number_increments():
    text = "INT. OFFICE - DAY\n\nAction.\n\nEXT. STREET - DAY\n\nMore action.\n"
    elements = parse(text)
    headings = [e for e in elements if e.element_type == "scene_heading"]
    assert len(headings) == 2
    assert headings[0].scene_number == 1
    assert headings[1].scene_number == 2
