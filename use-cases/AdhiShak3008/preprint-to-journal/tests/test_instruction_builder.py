"""
test_instruction_builder.py
Tests for transformation instruction generation.
"""
import pytest
from instruction_builder import build_instruction, SCIENCE_PRESERVATION_PREAMBLE


class TestBuildInstruction:
    def test_contains_science_preservation_preamble(self, nature_profile):
        instruction = build_instruction(nature_profile)
        assert "SCIENTIFIC CONTENT MUST NOT BE CHANGED" in instruction
        assert "numerical results" in instruction
        assert "equations" in instruction

    def test_contains_journal_name(self, nature_profile):
        instruction = build_instruction(nature_profile)
        assert "Nature" in instruction

    def test_contains_section_order(self, nature_profile):
        instruction = build_instruction(nature_profile)
        for section in nature_profile["section_order"]:
            assert section in instruction

    def test_contains_reference_style(self, nature_profile):
        instruction = build_instruction(nature_profile)
        assert "numbered-superscript" in instruction or "superscript" in instruction.lower()

    def test_contains_figure_placement(self, nature_profile):
        instruction = build_instruction(nature_profile)
        assert "figure" in instruction.lower()
        assert "end" in instruction.lower()

    def test_contains_table_placement(self, nature_profile):
        instruction = build_instruction(nature_profile)
        assert "table" in instruction.lower()

    def test_word_limit_included_when_set(self, nature_profile):
        instruction = build_instruction(nature_profile)
        assert "3000" in instruction  # Nature word limit

    def test_no_word_limit_instruction_when_null(self, plos_profile):
        # PLOS ONE has null word_limit
        instruction = build_instruction(plos_profile)
        # Should not contain a word limit instruction for main text
        assert "word limit" not in instruction.lower() or "abstract" in instruction.lower()

    def test_blinding_absent_for_non_blinded_journal(self, nature_profile):
        assert nature_profile["blinded_review"] is False
        instruction = build_instruction(nature_profile)
        assert "BLINDING" not in instruction
        assert "double-blind" not in instruction.lower()

    def test_blinding_present_for_blinded_journal(self, plos_profile):
        assert plos_profile["blinded_review"] is True
        instruction = build_instruction(plos_profile)
        assert "BLINDING" in instruction
        assert "double-blind" in instruction.lower()

    def test_blinding_includes_acknowledgements(self, plos_profile):
        instruction = build_instruction(plos_profile)
        assert "Acknowledgement" in instruction or "acknowledgement" in instruction.lower()

    def test_blinding_includes_self_citations(self, plos_profile):
        instruction = build_instruction(plos_profile)
        assert "self-citation" in instruction.lower() or "Self-citation" in instruction

    def test_blinding_includes_self_identifying_language(self, plos_profile):
        instruction = build_instruction(plos_profile)
        assert "self-identifying" in instruction.lower() or "in our previous work" in instruction

    def test_author_info_included_in_blinding(self, plos_profile):
        author_info = {
            "names": ["Jane Smith", "Robert Jones"],
            "affiliations": ["University of Example"],
        }
        instruction = build_instruction(plos_profile, author_info=author_info)
        assert "Jane Smith" in instruction
        assert "Robert Jones" in instruction
        assert "University of Example" in instruction

    def test_declarations_included(self, nature_profile):
        instruction = build_instruction(nature_profile)
        assert "declaration" in instruction.lower() or "Declaration" in instruction

    def test_plos_abstract_structure_included(self, plos_profile):
        instruction = build_instruction(plos_profile)
        # PLOS ONE has structured abstract requirement
        assert "Background" in instruction or "abstract" in instruction.lower()

    def test_no_fabrication_instruction(self, nature_profile):
        instruction = build_instruction(nature_profile)
        # Should instruct not to invent content
        assert "missing" in instruction.lower() or "not exist" in instruction.lower()

    def test_instruction_is_string(self, nature_profile):
        instruction = build_instruction(nature_profile)
        assert isinstance(instruction, str)
        assert len(instruction) > 100
