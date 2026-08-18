from dataclasses import dataclass, field


@dataclass
class BoardItem:
    id: str
    item_type: str
    text: str = ""
    parent_id: str | None = None


@dataclass
class Section:
    title: str
    source_ids: list[str] = field(default_factory=list)
    items: list[BoardItem] = field(default_factory=list)