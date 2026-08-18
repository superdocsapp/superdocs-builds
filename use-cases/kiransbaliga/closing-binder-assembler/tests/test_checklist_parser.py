"""Tests for M&A closing checklist parser."""

import os
import pytest

from core.enums import DocumentCategory, PriorityLevel
from parsers.checklist_parser import ChecklistParser


@pytest.fixture
def parser():
    return ChecklistParser()


def test_parse_json_checklist(parser):
    sample_json = os.path.join(os.path.dirname(__file__), "..", "samples", "project_titan_checklist.json")
    checklist = parser.parse_file(sample_json)

    assert checklist.deal_name.startswith("Project Titan")
    assert checklist.buyer_entity == "Apex Holdings LLC"
    assert checklist.target_entity == "CloudScale Technologies, Inc."
    assert len(checklist.items) >= 20

    item_01 = checklist.items[0]
    assert item_01.tab_number == 1
    assert item_01.title == "Agreement and Plan of Merger"
    assert item_01.signatures_required is True
    assert item_01.category == DocumentCategory.PRIMARY_AGREEMENT


def test_parse_markdown_checklist(parser):
    sample_md = os.path.join(os.path.dirname(__file__), "..", "samples", "project_titan_checklist.md")
    checklist = parser.parse_file(sample_md)

    assert "Project Titan" in checklist.deal_name
    assert len(checklist.items) >= 20
    assert checklist.items[0].title == "Agreement and Plan of Merger"
    assert checklist.items[1].title == "Escrow Agreement"
