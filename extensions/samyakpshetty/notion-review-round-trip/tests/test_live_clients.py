"""Keyless tests for the live clients: the Notion JSON mapping and protocol conformance.

The HTTP calls themselves are proven in the live run; here we test the pure mapping (no network)
and that the live clients satisfy the same protocols the fakes do — so ``PROVIDER=live`` is a
drop-in, verified structurally.
"""

from __future__ import annotations

from notion_review.notion.base import NotionClient
from notion_review.notion.live import (
    LiveNotionClient,
    block_from_json,
    page_title,
    rich_from_json,
    rich_to_json,
)
from notion_review.notion.models import Annotations, RichText
from notion_review.superdocs.base import SuperDocsClient
from notion_review.superdocs.live import LiveSuperDocsClient


def test_live_clients_satisfy_the_protocols() -> None:
    assert isinstance(LiveNotionClient(token="ntn_test"), NotionClient)
    assert isinstance(LiveSuperDocsClient(api_key="sk_test"), SuperDocsClient)


def test_rich_text_maps_both_ways() -> None:
    node = {
        "type": "text",
        "text": {"content": "Hello"},
        "annotations": {"bold": True, "italic": False, "code": False, "color": "default"},
        "plain_text": "Hello",
        "href": "https://example.com",
    }
    run = rich_from_json(node)
    assert run.text == "Hello"
    assert run.annotations.bold is True
    assert run.href == "https://example.com"

    out = rich_to_json(RichText(text="Bye", annotations=Annotations(italic=True), href="https://x"))
    assert out["text"] == {"content": "Bye", "link": {"url": "https://x"}}
    assert out["annotations"]["italic"] is True


def test_block_from_json_reads_paragraph_and_callout() -> None:
    paragraph = block_from_json(
        {
            "id": "b1",
            "type": "paragraph",
            "has_children": False,
            "paragraph": {"rich_text": [{"plain_text": "A line", "annotations": {}}]},
        }
    )
    assert paragraph.type == "paragraph"
    assert paragraph.plain() == "A line"

    callout = block_from_json(
        {
            "id": "b2",
            "type": "callout",
            "has_children": True,
            "callout": {
                "rich_text": [{"plain_text": "Heads up", "annotations": {}}],
                "icon": {"type": "emoji", "emoji": "💡"},
                "color": "blue_background",
            },
        }
    )
    assert callout.meta["icon"] == "💡"
    assert callout.meta["color"] == "blue_background"
    assert callout.has_children is True


def test_block_from_json_reads_table_row_cells() -> None:
    row = block_from_json(
        {
            "id": "b3",
            "type": "table_row",
            "table_row": {"cells": [[{"plain_text": "Plan"}], [{"plain_text": "Price"}]]},
        }
    )
    assert row.meta["cells"] == [["Plan"], ["Price"]]


def test_page_title_reads_the_title_property() -> None:
    data = {
        "id": "p1",
        "url": "https://notion.so/p1",
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Project Aurora"}]},
        },
    }
    assert page_title(data) == "Project Aurora"
