from miro_parser import get_board_items, parse_items
from models import BoardItem, Section


def build_board_structure(items):
    """
    Build a normalized representation of the Miro board.

    We currently use parent IDs to group sticky notes.
    We deliberately keep the original Miro IDs so every
    generated section can be traced back to its source.
    """

    sections = {}

    for item in items:

        if item["type"] != "sticky_note":
            continue

        parent_id = item["parent_id"]

        if parent_id not in sections:
            sections[parent_id] = Section(
                title=f"Group {len(sections) + 1}"
            )

        board_item = BoardItem(
            id=item["id"],
            item_type=item["type"],
            text=item["text"],
            parent_id=parent_id,
        )

        sections[parent_id].items.append(board_item)
        sections[parent_id].source_ids.append(item["id"])

    return list(sections.values())


if __name__ == "__main__":

    raw_items = get_board_items()
    parsed_items = parse_items(raw_items)

    sections = build_board_structure(parsed_items)

    print("\n========== STRUCTURED BOARD ==========\n")

    for section in sections:

        print(f"SECTION: {section.title}")
        print(f"SOURCES: {len(section.source_ids)}")

        for item in section.items:
            print(f"  - {item.text}")

        print("-" * 50)