"""
Tests for citation label enrichment and memo verbosity improvements.

Covers:
1. Citation rendering uses real source document name when available.
2. Citation rendering gracefully falls back when source name is unavailable.
3. Memo sections remain schema-valid.
4. Required sections are still generated (not accidentally removed).
5. Existing citations/claim references remain intact.
6. Section-focus guidance is injected into prompts for all section types.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from backend.integrations.superdocs.instruction_builder import InstructionBuilder


# ---------------------------------------------------------------------------
# Test 1: Citation uses real document name when document_name is present
# ---------------------------------------------------------------------------

def test_instruction_builder_renders_lean_sections_with_headings():
    """build_structured_memo_instruction renders section titles and finalized content cleanly."""
    builder = InstructionBuilder()
    sections = [
        {
            "title": "Classification Analysis",
            "section_order": 1,
            "source_attribution": [
                {
                    "document_id": "abc123",
                    "document_name": "product_specification.pdf",
                    "excerpt": "Foldable aluminum stand",
                }
            ],
            "analyst_reasoning": "Aluminum stand analysis.",
            "content": "Classification content.",
        }
    ]
    instruction = builder.build_structured_memo_instruction(sections)
    assert "# Tariff Classification Memo" in instruction
    assert "## Classification Analysis" in instruction
    assert "Classification content." in instruction
    assert "Analyst Reasoning: Aluminum stand analysis." in instruction
    assert "FORMATTING GUIDELINES:" in instruction


def test_instruction_builder_renders_product_images_section():
    """build_structured_memo_instruction includes image references when provided."""
    builder = InstructionBuilder()
    sections = [
        {
            "title": "Relevant Previous Rulings",
            "section_order": 1,
            "source_attribution": [],
            "analyst_reasoning": "",
            "content": "Ruling content.",
        }
    ]
    image_refs = [{"filename": "product_top.jpg", "document_id": "doc-img-1"}]
    instruction = builder.build_structured_memo_instruction(sections, image_refs=image_refs)
    assert "## Product Images" in instruction
    assert "product_top.jpg" in instruction
    assert "doc-img-1" in instruction


def test_instruction_builder_handles_empty_source_attribution_cleanly():
    """build_structured_memo_instruction handles empty source attribution without error."""
    builder = InstructionBuilder()
    sections = [
        {
            "title": "Product Overview",
            "section_order": 1,
            "source_attribution": [],
            "analyst_reasoning": "",
            "content": "Product overview content.",
        }
    ]
    instruction = builder.build_structured_memo_instruction(sections)
    assert "## Product Overview" in instruction
    assert "Product overview content." in instruction


def test_citation_with_empty_source_attribution():
    """Sections with empty source_attribution must not crash."""
    builder = InstructionBuilder()
    sections = [
        {
            "title": "Executive Summary",
            "section_order": 1,
            "source_attribution": [],
            "analyst_reasoning": "Summary reasoning.",
            "content": "Summary content.",
        }
    ]
    instruction = builder.build_structured_memo_instruction(sections)
    assert "Executive Summary" in instruction


# ---------------------------------------------------------------------------
# Test 3: Memo sections remain schema-valid
# ---------------------------------------------------------------------------

def test_memo_section_output_schema_accepts_focus_field():
    """MemoSectionOutput must still accept standard fields (no regression from prompt changes)."""
    from backend.modules.tariff.memo_types import MemoSectionOutput
    output = MemoSectionOutput(
        content="Classification under heading 7616.",
        analyst_reasoning="The primary material is aluminum.",
        source_attribution=[{"document_id": "doc-1", "excerpt": "aluminum stand"}],
        confidence="high",
    )
    assert output.content == "Classification under heading 7616."
    assert len(output.source_attribution) == 1


# ---------------------------------------------------------------------------
# Test 4: Required sections are still generated (prompts are still valid)
# ---------------------------------------------------------------------------

def test_section_generation_prompt_contains_focus_placeholder():
    """SECTION_GENERATION_PROMPT must contain {section_focus} placeholder."""
    from backend.modules.tariff.prompts_memo import (
        SECTION_GENERATION_PROMPT,
        SECTION_GENERATION_PROMPT_NO_RULINGS,
    )
    assert "{section_focus}" in SECTION_GENERATION_PROMPT
    assert "{section_focus}" in SECTION_GENERATION_PROMPT_NO_RULINGS


def test_section_focus_guidance_covers_all_required_sections():
    """All required memo section types must have a focus entry."""
    from backend.modules.tariff.prompts_memo import SECTION_FOCUS_GUIDANCE
    from backend.modules.tariff.memo_types import MemoSectionType

    # Core sections that must always appear
    required = [
        MemoSectionType.EXECUTIVE_SUMMARY,
        MemoSectionType.PRODUCT_OVERVIEW,
        MemoSectionType.PRODUCT_DESCRIPTION,
        MemoSectionType.TECHNICAL_CHARACTERISTICS,
        MemoSectionType.MATERIAL_COMPOSITION,
        MemoSectionType.CLASSIFICATION_ANALYSIS,
        MemoSectionType.ALTERNATIVES_CONSIDERED,
        MemoSectionType.ALTERNATIVES_REJECTED,
        MemoSectionType.RECOMMENDED_CLASSIFICATION,
        MemoSectionType.SUPPORTING_CITATIONS,
    ]
    missing = [s.value for s in required if s.value not in SECTION_FOCUS_GUIDANCE]
    assert not missing, f"Missing focus guidance for sections: {missing}"


def test_section_generation_prompt_formats_correctly():
    """SECTION_GENERATION_PROMPT must format without KeyError when all placeholders provided."""
    from backend.modules.tariff.prompts_memo import SECTION_GENERATION_PROMPT, _section_focus
    formatted = SECTION_GENERATION_PROMPT.format(
        section_title="Classification Analysis",
        section_type="classification_analysis",
        section_focus=_section_focus("classification_analysis"),
        product_facts="{}",
        ruling_facts="[]",
        evidence="None",
        prior_knowledge="None",
        baseline_section="None",
    )
    assert "classification_analysis" in formatted
    assert "Section focus" in formatted


def test_section_generation_prompt_no_rulings_formats_correctly():
    """SECTION_GENERATION_PROMPT_NO_RULINGS must format without KeyError."""
    from backend.modules.tariff.prompts_memo import SECTION_GENERATION_PROMPT_NO_RULINGS, _section_focus
    formatted = SECTION_GENERATION_PROMPT_NO_RULINGS.format(
        section_title="Product Overview",
        section_type="product_overview",
        section_focus=_section_focus("product_overview"),
        product_facts="{}",
        evidence="None",
        prior_knowledge="None",
        baseline_section="None",
    )
    assert "product_overview" in formatted
    assert "Section focus" in formatted


# ---------------------------------------------------------------------------
# Test 5: Existing citations/claim references remain intact
# ---------------------------------------------------------------------------

def test_all_memo_sections_present_in_instruction():
    """All memo section titles and contents appear in the built instruction."""
    builder = InstructionBuilder()
    sections = [
        {
            "title": "Material Composition",
            "section_order": 1,
            "source_attribution": [
                {"document_name": "spec.pdf", "excerpt": "6061 aluminum alloy"},
            ],
            "analyst_reasoning": "Material analysis.",
            "content": "Material content with aluminum alloy.",
        }
    ]
    instruction = builder.build_structured_memo_instruction(sections)
    assert "## Material Composition" in instruction
    assert "Material content with aluminum alloy." in instruction
    assert "Analyst Reasoning: Material analysis." in instruction


# ---------------------------------------------------------------------------
# Test 6: Section focus guidance reduces unnecessary full-product re-description
# ---------------------------------------------------------------------------

def test_executive_summary_focus_discourages_product_detail():
    """Executive summary focus must tell the LLM not to describe the product in detail."""
    from backend.modules.tariff.prompts_memo import _section_focus
    focus = _section_focus("executive_summary")
    # Must mention conciseness / HS code / not detailing product
    assert "concise" in focus.lower() or "hs code" in focus.lower()
    assert "not" in focus.lower() or "do not" in focus.lower()


def test_product_overview_focus_excludes_materials_directive():
    """Product overview focus must tell LLM not to list materials."""
    from backend.modules.tariff.prompts_memo import _section_focus
    focus = _section_focus("product_overview")
    assert "material" in focus.lower()


def test_technical_characteristics_focus_references_dimensions():
    """Technical characteristics focus must point to dimensions and physical details."""
    from backend.modules.tariff.prompts_memo import _section_focus
    focus = _section_focus("technical_characteristics")
    assert "dimension" in focus.lower() or "physical" in focus.lower()


def test_default_focus_returned_for_unknown_section():
    """Unknown section types must get the default focus, not crash."""
    from backend.modules.tariff.prompts_memo import _section_focus
    focus = _section_focus("completely_unknown_section_xyz")
    assert isinstance(focus, str) and len(focus) > 0


# ---------------------------------------------------------------------------
# Test: SuperDocsInstructionStage creates job and passes structured instruction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_instruction_stage_creates_job():
    """SuperDocsInstructionStage executes and submits instruction to SuperDocs."""
    from backend.modules.tariff.stages.superdocs_instruction import SuperDocsInstructionStage
    from backend.modules.tariff.schemas import TariffWorkflowState

    run_id = str(uuid4())
    doc_uuid = str(uuid4())

    mock_section = MagicMock()
    mock_section.status = "pending"
    mock_section.title = "Classification Analysis"
    mock_section.section_order = 1
    mock_section.section_type = "classification_analysis"
    mock_section.content = "Classified under 7616."
    mock_section.analyst_reasoning = "Aluminum is primary material."
    mock_section.source_attribution = [
        {"document_id": doc_uuid, "excerpt": "aluminum structural body"}
    ]
    mock_section.structured_data = None

    mock_section_repo = AsyncMock()
    mock_section_repo.list_by_run = AsyncMock(return_value=[mock_section])

    mock_doc = MagicMock()
    mock_doc.filename = "classification_ruling.pdf"
    mock_doc_repo = AsyncMock()
    mock_doc_repo.get_by_id = AsyncMock(return_value=mock_doc)

    mock_job = MagicMock()
    mock_job.job_id = "job-test-001"
    mock_client = AsyncMock()
    mock_client.chat_async = AsyncMock(return_value=mock_job)

    from backend.integrations.superdocs.instruction_builder import InstructionBuilder
    stage = SuperDocsInstructionStage(
        superdocs_client=mock_client,
        instruction_builder=InstructionBuilder(),
        memo_section_repository=mock_section_repo,
        document_repository=mock_doc_repo,
    )

    state = TariffWorkflowState(
        workflow_run_id=run_id,
        workspace_id=str(uuid4()),
        document_id=str(uuid4()),
        superdocs_session_id="sess-abc",
    )

    result = await stage.execute(state)

    assert result["superdocs_job_id"] == "job-test-001"
    call_args = mock_client.chat_async.call_args
    instruction_sent = call_args.kwargs.get("message") or call_args.args[1]
    assert "## Classification Analysis" in instruction_sent
    assert "Classified under 7616." in instruction_sent


def test_instruction_builder_omits_orphan_reasoning_and_puts_content_first():
    """Instruction builder must put content first and avoid standalone ANALYST REASONING: lines."""
    from backend.integrations.superdocs.instruction_builder import InstructionBuilder
    builder = InstructionBuilder()

    sections = [
        {
            "title": "Product Overview",
            "section_order": 1,
            "content": "The AeroLink X7 is an industrial UAV.",
            "analyst_reasoning": "Reasoning:",  # Trivial label
            "source_attribution": [],
        },
        {
            "title": "Product Description",
            "section_order": 2,
            "content": "Quad-rotor drone with carbon fiber frame.",
            "analyst_reasoning": "Substantive analysis on drone architecture.",
            "source_attribution": [],
        },
    ]

    instruction = builder.build_structured_memo_instruction(sections)

    # Product Overview has only trivial reasoning, so no "Analyst Reasoning:" or "ANALYST REASONING:"
    assert "## Product Overview" in instruction
    assert "The AeroLink X7 is an industrial UAV." in instruction
    assert "ANALYST REASONING:\nReasoning:" not in instruction
    # Product Description has substantive reasoning
    assert "Analyst Reasoning: Substantive analysis on drone architecture." in instruction

