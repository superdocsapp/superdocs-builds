from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

HEADING_STYLES = frozenset(
    {
        "TITLE",
        "SUBTITLE",
        "HEADING_1",
        "HEADING_2",
        "HEADING_3",
        "HEADING_4",
        "HEADING_5",
        "HEADING_6",
    }
)


class PreviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FrozenPreviewBlock(PreviewModel):
    kind: Literal["paragraph", "heading"]
    named_style: str | None = None
    text: str = Field(min_length=1)


class FrozenDocumentPreview(PreviewModel):
    available: bool
    revision_id: str
    blocks: tuple[FrozenPreviewBlock, ...] = ()


def preview_from_canonical(
    canonical_payload: Any,
    *,
    revision_id: str,
) -> FrozenDocumentPreview:
    """Presentation-only projection of a frozen native snapshot.

    Walks persisted canonical body paragraphs. Does not call Google, invent
    missing structure, or flatten tables into fake body copy.
    """
    if not revision_id:
        return FrozenDocumentPreview(available=False, revision_id="", blocks=())

    tabs = canonical_payload.get("tabs") if isinstance(canonical_payload, dict) else None
    if not isinstance(tabs, list):
        return FrozenDocumentPreview(available=False, revision_id=revision_id, blocks=())

    blocks: list[FrozenPreviewBlock] = []
    for tab in tabs:
        if not isinstance(tab, dict):
            continue
        body = tab.get("body")
        if not isinstance(body, list):
            continue
        for element in body:
            block = _block_from_element(element)
            if block is not None:
                blocks.append(block)

    return FrozenDocumentPreview(
        available=len(blocks) > 0,
        revision_id=revision_id,
        blocks=tuple(blocks),
    )


def _block_from_element(element: Any) -> FrozenPreviewBlock | None:
    if not isinstance(element, dict) or element.get("type") != "paragraph":
        return None
    text = _paragraph_plain_text(element)
    if not text:
        return None
    style = element.get("paragraphStyle")
    named = style.get("namedStyleType") if isinstance(style, dict) else None
    named_style = named if isinstance(named, str) and named else None
    kind: Literal["paragraph", "heading"] = (
        "heading" if named_style in HEADING_STYLES else "paragraph"
    )
    return FrozenPreviewBlock(kind=kind, named_style=named_style, text=text)


def _paragraph_plain_text(paragraph: dict[str, Any]) -> str | None:
    runs = paragraph.get("runs")
    if not isinstance(runs, list):
        return None
    parts: list[str] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("kind") != "text":
            continue
        value = run.get("text")
        if isinstance(value, str):
            parts.append(value)
    text = "".join(parts).replace("\u000b", "\n").rstrip("\n").strip()
    return text or None
