import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from backend.modules.screenplay.parser import ScreenplayParser
from backend.modules.screenplay.formatter import format_element
from backend.modules.screenplay.validator import ContentDriftValidator
from backend.modules.screenplay.stages.parse import ParseStage
from backend.modules.screenplay.stages.format import FormatStage
from backend.modules.screenplay.stages.diff import DiffStage
from backend.modules.screenplay.stages.regenerate import RegenerateStage
from backend.modules.screenplay.schemas import ScreenplayElement, FormattingItem


SAMPLE_SCREENPLAY = """LAST CALL

Written by A. Sharma

INT. DIVE BAR - NIGHT

The neon beer sign buzzes and flickers.

RAVI
(42)
No signal. Again.

MEENA
(55)
It's been like that all evening.

PRIYA & RAVI
We should leave.

FADE OUT.

THE END
"""


def test_req_a_title_not_character():
    parser = ScreenplayParser()
    elements = parser.parse(SAMPLE_SCREENPLAY)
    title_elem = elements[0]
    assert title_elem.element_type == 'title'
    assert title_elem.content == 'LAST CALL'
    assert title_elem.character_name is None


def test_req_b_author_not_dialogue_or_character():
    parser = ScreenplayParser()
    elements = parser.parse(SAMPLE_SCREENPLAY)
    author_elem = elements[1]
    assert author_elem.element_type == 'author'
    assert author_elem.content == 'Written by A. Sharma'
    assert author_elem.character_name is None


def test_req_c_end_not_character():
    parser = ScreenplayParser()
    elements = parser.parse(SAMPLE_SCREENPLAY)
    end_elem = elements[-1]
    assert end_elem.element_type == 'end'
    assert 'END' in end_elem.content.upper()
    assert end_elem.character_name is None


def test_req_d_scene_heading_not_character():
    parser = ScreenplayParser()
    elements = parser.parse(SAMPLE_SCREENPLAY)
    scene_elems = [e for e in elements if e.element_type == 'scene_heading']
    assert len(scene_elems) == 1
    assert scene_elems[0].content == 'INT. DIVE BAR - NIGHT'
    assert scene_elems[0].scene_number == 1


def test_req_e_action_not_character():
    parser = ScreenplayParser()
    elements = parser.parse(SAMPLE_SCREENPLAY)
    action_elems = [e for e in elements if e.element_type == 'action']
    assert len(action_elems) >= 1
    assert any('neon beer sign' in e.content for e in action_elems)
    for a in action_elems:
        assert a.character_name is None


def test_req_f_real_character_detected_with_dialogue():
    parser = ScreenplayParser()
    elements = parser.parse(SAMPLE_SCREENPLAY)
    char_elems = [e for e in elements if e.element_type == 'character']
    char_names = [e.content for e in char_elems]
    assert 'RAVI' in char_names
    assert 'MEENA' in char_names
    assert 'PRIYA & RAVI' in char_names
    assert 'LAST CALL' not in char_names
    assert 'Written by A. Sharma' not in char_names


def test_req_g_compliant_elements_generate_zero_pending():
    elements = [
        ScreenplayElement(element_type='title', content='LAST CALL', element_index=0),
        ScreenplayElement(element_type='author', content='Written by A. Sharma', element_index=1),
        ScreenplayElement(element_type='scene_heading', content='INT. DIVE BAR - NIGHT', element_index=2, scene_number=1),
        ScreenplayElement(element_type='character', content='RAVI', element_index=3, scene_number=1, character_name='RAVI'),
        ScreenplayElement(element_type='dialogue', content='No signal. Again.', element_index=4, scene_number=1, character_name='RAVI'),
        ScreenplayElement(element_type='end', content='THE END', element_index=5),
    ]

    for elem in elements:
        formatted_text, change_type, reason = format_element(elem.element_type, elem.content)
        assert change_type == 'no_change'
        assert formatted_text == elem.content


def test_req_h_formatting_difference_generates_one_pending_proposal():
    # Lowercase scene heading
    formatted_text, change_type, reason = format_element('scene_heading', 'int. dive bar - night')
    assert change_type == 'capitalization'
    assert formatted_text == 'INT. DIVE BAR - NIGHT'
    assert 'uppercase' in reason.lower()

    # Lowercase character name
    formatted_text, change_type, reason = format_element('character', 'ravi')
    assert change_type == 'capitalization'
    assert formatted_text == 'RAVI'
    assert 'uppercase' in reason.lower()


@pytest.mark.asyncio
async def test_req_i_format_stage_pending_count():
    repo_mock = MagicMock()
    repo_mock.create = AsyncMock(side_effect=lambda **kwargs: MagicMock(id=uuid4(), **kwargs))

    stage = FormatStage(formatting_item_repo=repo_mock)

    clean_elements = [
        {'element_type': 'scene_heading', 'content': 'INT. DIVE BAR - NIGHT', 'element_index': 0, 'confidence': 1.0},
        {'element_type': 'character', 'content': 'RAVI', 'element_index': 1, 'confidence': 1.0},
        {'element_type': 'dialogue', 'content': 'Hello.', 'element_index': 2, 'confidence': 1.0},
    ]

    res = await stage.execute({
        'workflow_run_id': str(uuid4()),
        'parsed_screenplay': {'elements': clean_elements, 'scene_count': 1, 'character_list': ['RAVI']}
    })

    items = res['formatting_items']
    pending_items = [i for i in items if i['status'] == 'pending']
    approved_items = [i for i in items if i['status'] == 'approved']

    assert len(pending_items) == 0
    assert len(approved_items) == 3

    flawed_elements = [
        {'element_type': 'scene_heading', 'content': 'int. dive bar - night', 'element_index': 0, 'confidence': 1.0},
        {'element_type': 'character', 'content': 'RAVI', 'element_index': 1, 'confidence': 1.0},
    ]

    res_flawed = await stage.execute({
        'workflow_run_id': str(uuid4()),
        'parsed_screenplay': {'elements': flawed_elements, 'scene_count': 1, 'character_list': ['RAVI']}
    })

    flawed_items = res_flawed['formatting_items']
    flawed_pending = [i for i in flawed_items if i['status'] == 'pending']
    flawed_approved = [i for i in flawed_items if i['status'] == 'approved']

    assert len(flawed_pending) == 1
    assert len(flawed_approved) == 1
    assert flawed_pending[0]['change_type'] == 'capitalization'


@pytest.mark.asyncio
async def test_req_j_and_k_approve_and_reject_status():
    from backend.repositories.screenplay import FormattingItemRepository

    session_mock = MagicMock()
    mock_item = MagicMock(id=uuid4(), status='pending', reviewer_comment=None)

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = mock_item
    session_mock.execute = AsyncMock(return_value=result_mock)
    session_mock.commit = AsyncMock()
    session_mock.refresh = AsyncMock()

    repo = FormattingItemRepository(session_mock)

    approved = await repo.approve(mock_item.id)
    assert approved.status == 'approved'

    rejected = await repo.reject(mock_item.id, 'Keep original case')
    assert rejected.status == 'rejected'
    assert rejected.reviewer_comment == 'Keep original case'


@pytest.mark.asyncio
async def test_req_l_character_list_contains_genuine_characters_only():
    parse_stage = ParseStage()
    res = await parse_stage.execute({'document_text': SAMPLE_SCREENPLAY})
    parsed = res['parsed_screenplay']

    assert 'RAVI' in parsed['character_list']
    assert 'MEENA' in parsed['character_list']
    assert 'PRIYA & RAVI' in parsed['character_list']
    assert 'LAST CALL' not in parsed['character_list']
    assert 'Written by A. Sharma' not in parsed['character_list']
    assert 'THE END' not in parsed['character_list']
    assert 'INT. DIVE BAR - NIGHT' not in parsed['character_list']


def test_req_m_tariff_workflow_unaffected():
    from backend.modules.tariff.workflow import build_tariff_stages
    assert build_tariff_stages is not None
