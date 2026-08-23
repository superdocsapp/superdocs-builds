"""
test_blinding.py
Tests for blinding instruction building and blinding analysis.
"""
import pytest
from blinding import (
    build_blinding_instruction,
    analyse_blinding,
    BLINDING_LIMITATION,
)
from instruction_builder import build_instruction


class TestBuildBlindingInstruction:
    def test_contains_author_removal(self):
        instruction = build_blinding_instruction()
        assert "author" in instruction.lower()
        assert "[AUTHOR REMOVED]" in instruction

    def test_contains_affiliation_removal(self):
        instruction = build_blinding_instruction()
        assert "affiliation" in instruction.lower()
        assert "[AFFILIATION REMOVED]" in instruction

    def test_contains_acknowledgements_removal(self):
        instruction = build_blinding_instruction()
        assert "Acknowledgement" in instruction or "acknowledgement" in instruction.lower()
        assert "ACKNOWLEDGEMENTS REMOVED" in instruction

    def test_contains_funding_removal(self):
        instruction = build_blinding_instruction()
        assert "funding" in instruction.lower()
        assert "FUNDING DETAILS REMOVED" in instruction

    def test_contains_self_citation_removal(self):
        instruction = build_blinding_instruction()
        assert "self-citation" in instruction.lower() or "Self-citation" in instruction
        assert "SELF-CITATION REMOVED" in instruction

    def test_contains_self_identifying_language(self):
        instruction = build_blinding_instruction()
        assert "self-identifying" in instruction.lower()
        assert "in our previous work" in instruction

    def test_contains_contact_details_removal(self):
        instruction = build_blinding_instruction()
        assert "contact" in instruction.lower()
        assert "CONTACT DETAILS REMOVED" in instruction

    def test_author_names_included_when_provided(self):
        author_info = {"names": ["Jane Smith", "Robert Jones"], "affiliations": []}
        instruction = build_blinding_instruction(author_info)
        assert "Jane Smith" in instruction
        assert "Robert Jones" in instruction

    def test_affiliations_included_when_provided(self):
        author_info = {"names": [], "affiliations": ["University of Example"]}
        instruction = build_blinding_instruction(author_info)
        assert "University of Example" in instruction

    def test_no_author_info_still_produces_instruction(self):
        instruction = build_blinding_instruction(None)
        assert len(instruction) > 100
        assert "[AUTHOR REMOVED]" in instruction


class TestAnalyseBlinding:
    def test_detects_author_placeholder(self):
        html = "<p>[AUTHOR REMOVED] conducted the study.</p>"
        result = analyse_blinding(html)
        assert any("Author name placeholder" in item for item in result["items_removed"])

    def test_detects_affiliation_placeholder(self):
        html = "<p>From [AFFILIATION REMOVED].</p>"
        result = analyse_blinding(html)
        assert any("Affiliation placeholder" in item for item in result["items_removed"])

    def test_detects_acknowledgements_removed(self):
        html = "<p>[ACKNOWLEDGEMENTS REMOVED FOR BLIND REVIEW — to be restored]</p>"
        result = analyse_blinding(html)
        assert any("Acknowledgements removed" in item for item in result["items_removed"])

    def test_detects_self_citation_removed(self):
        html = "<p>[SELF-CITATION REMOVED FOR BLIND REVIEW]</p>"
        result = analyse_blinding(html)
        assert any("Self-citation" in item for item in result["items_removed"])

    def test_flags_remaining_our_group(self):
        html = "<p>As shown by our group previously.</p>"
        result = analyse_blinding(html)
        assert any("our group" in item.lower() or "our lab" in item.lower()
                   for item in result["potential_remaining"])

    def test_flags_remaining_in_our_previous_work(self):
        html = "<p>In our previous work, we demonstrated this effect.</p>"
        result = analyse_blinding(html)
        assert any("previous" in item.lower() for item in result["potential_remaining"])

    def test_flags_remaining_email(self):
        html = "<p>Contact: author@example.com for correspondence.</p>"
        result = analyse_blinding(html)
        assert any("email" in item.lower() for item in result["potential_remaining"])

    def test_flags_known_author_name_remaining(self):
        html = "<p>Smith et al. previously reported this finding.</p>"
        author_info = {"names": ["Jane Smith"], "affiliations": []}
        result = analyse_blinding(html, author_info)
        assert any("Smith" in item for item in result["potential_remaining"])

    def test_clean_html_no_remaining(self):
        html = (
            "<p>[AUTHOR REMOVED] conducted the study at [AFFILIATION REMOVED].</p>"
            "<p>[ACKNOWLEDGEMENTS REMOVED FOR BLIND REVIEW]</p>"
            "<p>Previous research demonstrated this effect [CITATION REMOVED].</p>"
        )
        result = analyse_blinding(html)
        assert len(result["items_removed"]) > 0
        # No obvious remaining identifiers
        assert len(result["potential_remaining"]) == 0

    def test_limitation_notice_always_present(self):
        result = analyse_blinding("<p>Some text.</p>")
        assert result["limitation_notice"] == BLINDING_LIMITATION

    def test_non_blinded_journal_no_blinding_in_instruction(self, nature_profile):
        assert nature_profile["blinded_review"] is False
        instruction = build_instruction(nature_profile)
        assert "BLINDING" not in instruction

    def test_blinded_journal_has_blinding_in_instruction(self, plos_profile):
        assert plos_profile["blinded_review"] is True
        instruction = build_instruction(plos_profile)
        assert "BLINDING" in instruction
        assert "Acknowledgement" in instruction or "acknowledgement" in instruction.lower()
