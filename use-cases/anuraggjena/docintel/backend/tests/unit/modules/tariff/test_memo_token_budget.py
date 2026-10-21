"""Tests for compact memo prompt building and dynamic token budget management.

RED phase: these tests define the desired behavior before implementation.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from backend.modules.tariff.stages.generate_memo_sections import (
    GenerateMemoSectionsStage,
    GROQ_TPM_LIMIT,
    TOKEN_SAFETY_MARGIN,
    CHARS_PER_TOKEN,
)
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.modules.tariff.memo_types import (
    MemoSectionType,
    MemoSectionOutput,
    ProductFacts,
    RulingFacts,
)


def _base_state(**kwargs):
    defaults = {
        "workflow_run_id": str(uuid4()),
        "workspace_id": "00000000-0000-0000-0000-000000000002",
    }
    defaults.update(kwargs)
    return TariffWorkflowState(**defaults)


def _mock_memo_service():
    service = AsyncMock()
    section = MagicMock(id=uuid4())
    claim = MagicMock(id=uuid4())
    service.create_section_with_claim = AsyncMock(return_value=(section, claim))
    service._section_repo = AsyncMock()
    service._section_repo.get_by_run_and_type = AsyncMock(return_value=None)
    service._section_repo.update = AsyncMock()
    service._claim_repo = AsyncMock()
    service._claim_repo.list_by_run = AsyncMock(return_value=[])
    return service


# ---------------------------------------------------------------------------
# 1. Compact prompt: sections that don't need ruling facts omit them
# ---------------------------------------------------------------------------

def test_product_overview_prompt_omits_ruling_facts():
    """product_overview section prompt must not include full ruling JSON."""
    stage = GenerateMemoSectionsStage()
    state = _base_state(
        product_facts=ProductFacts(product_name="Widget"),
        ruling_facts=[
            RulingFacts(ruling_number="HQ-001", reasoning="Detailed ruling reasoning " * 50)
        ],
    )
    prompt = stage._build_prompt(MemoSectionType.PRODUCT_OVERVIEW, state)
    # product_overview is a factual description section — ruling details not needed
    assert "HQ-001" not in prompt
    assert len(prompt) < 3000


def test_classification_analysis_prompt_includes_ruling_facts():
    """classification_analysis must include ruling facts for grounding."""
    stage = GenerateMemoSectionsStage()
    state = _base_state(
        product_facts=ProductFacts(product_name="Widget"),
        ruling_facts=[RulingFacts(ruling_number="HQ-001", reasoning="GRI 1 applies")],
    )
    prompt = stage._build_prompt(MemoSectionType.CLASSIFICATION_ANALYSIS, state)
    assert "HQ-001" in prompt


def test_evidence_chunks_are_section_relevant():
    """Only evidence chunks tagged for the section (or top-2 generic) are included."""
    stage = GenerateMemoSectionsStage()
    chunks = [
        {"text": "aluminum alloy composition", "section_relevance": ["material_composition"]},
        {"text": "GRI 3b applies here", "section_relevance": ["classification_analysis"]},
        {"text": "product dimensions 250mm", "section_relevance": ["technical_characteristics"]},
        {"text": "generic background info", "section_relevance": []},
    ]
    state = _base_state(
        product_facts=ProductFacts(product_name="Widget"),
        retrieved_chunks=chunks,
    )
    prompt = stage._build_prompt(MemoSectionType.MATERIAL_COMPOSITION, state)
    assert "aluminum alloy composition" in prompt
    # GRI analysis not needed for material_composition
    assert "GRI 3b applies here" not in prompt


# ---------------------------------------------------------------------------
# 2. Dynamic max_tokens: safe within Groq TPM budget
# ---------------------------------------------------------------------------

def test_dynamic_max_tokens_leaves_room_for_output():
    """max_tokens must be positive and input + max_tokens <= TPM limit."""
    stage = GenerateMemoSectionsStage()
    prompt = "A" * 3000  # ~750 tokens
    max_tok = stage._safe_max_tokens(prompt)
    estimated_input = len(prompt) // CHARS_PER_TOKEN
    assert max_tok > 0
    assert estimated_input + max_tok <= GROQ_TPM_LIMIT


def test_dynamic_max_tokens_respects_safety_margin():
    """Available tokens must include safety margin."""
    stage = GenerateMemoSectionsStage()
    prompt = "A" * 1000  # ~250 tokens
    max_tok = stage._safe_max_tokens(prompt)
    estimated_input = len(prompt) // CHARS_PER_TOKEN
    assert max_tok <= GROQ_TPM_LIMIT - estimated_input - TOKEN_SAFETY_MARGIN


def test_dynamic_max_tokens_has_floor_of_512():
    """Even with a large prompt, max_tokens must be at least 512 to get a valid JSON."""
    stage = GenerateMemoSectionsStage()
    # prompt of ~6000 chars = ~1500 tokens — leaves ~6500 but we cap at reasonable value
    prompt = "A" * 6000
    max_tok = stage._safe_max_tokens(prompt)
    assert max_tok >= 512


# ---------------------------------------------------------------------------
# 3. Oversized prompt handling: prompt is trimmed, not aborted
# ---------------------------------------------------------------------------

def test_oversized_prompt_is_trimmed_to_fit():
    """A prompt exceeding the safe input budget must be trimmed before sending."""
    stage = GenerateMemoSectionsStage()
    # ~10000 chars of evidence would produce ~2500 tokens of input
    massive_evidence = "evidence " * 1000
    state = _base_state(
        product_facts=ProductFacts(product_name="Widget"),
        retrieved_chunks=[{"text": massive_evidence, "section_relevance": []}],
    )
    prompt = stage._build_prompt(MemoSectionType.PRODUCT_OVERVIEW, state)
    estimated_tokens = len(prompt) // CHARS_PER_TOKEN
    # After trimming, input must leave at least 512 tokens for output
    assert estimated_tokens <= GROQ_TPM_LIMIT - 512


# ---------------------------------------------------------------------------
# 4. Valid structured output from the LLM call path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_section_uses_dynamic_max_tokens():
    """The LLM call must receive max_tokens computed dynamically from prompt size."""
    svc = _mock_memo_service()
    stage = GenerateMemoSectionsStage(memo_section_service=svc)
    state = _base_state(product_facts=ProductFacts(product_name="Widget"))
    output = MemoSectionOutput(content="text", analyst_reasoning="reason")
    captured = {}

    async def fake_generate_structured(messages, model, response_schema, temperature, max_tokens):
        captured["max_tokens"] = max_tokens
        captured["prompt_len"] = sum(len(m.content) for m in messages)
        return output

    with patch.object(stage.llm, "generate_structured", side_effect=fake_generate_structured):
        await stage.execute(state)

    assert "max_tokens" in captured
    estimated_input = captured["prompt_len"] // CHARS_PER_TOKEN
    assert estimated_input + captured["max_tokens"] <= GROQ_TPM_LIMIT


# ---------------------------------------------------------------------------
# 5. Idempotent retry: completed sections are reused without an LLM call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_completed_sections_reused_on_retry():
    """When a section already has status=pending/completed in DB, LLM is not called again."""
    svc = _mock_memo_service()
    existing = MagicMock()
    existing.id = uuid4()
    existing.status = "pending"
    existing.content = "Previously generated content"

    # All sections already exist
    svc._section_repo.get_by_run_and_type = AsyncMock(return_value=existing)
    svc._claim_repo.list_by_run = AsyncMock(return_value=[
        MagicMock(
            id=uuid4(),
            source_stage="generate_memo_sections",
            content=str(existing.id),
        )
    ])

    stage = GenerateMemoSectionsStage(memo_section_service=svc)
    state = _base_state(product_facts=ProductFacts(product_name="Widget"))
    output = MemoSectionOutput(content="new content", analyst_reasoning="reason")

    with patch.object(stage.llm, "generate_structured", new=AsyncMock(return_value=output)) as mock_llm:
        result = await stage.execute(state)

    # LLM must NOT be called when all sections exist and are not marked for regeneration
    assert mock_llm.call_count == 0
    assert result["generate_memo_completed"] is True
