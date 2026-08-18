from collections import defaultdict

from miro_parser import get_board_items, parse_items


def group_sticky_notes(items):
    """Group sticky notes by their Miro parent/container ID."""

    groups = defaultdict(list)

    for item in items:

        if item["type"] != "sticky_note":
            continue

        groups[item["parent_id"]].append({
            "id": item["id"],
            "text": item["text"],
        })

    return groups


def find_text_items(items):
    """Return board text items that may contain headings or content."""

    return [
        item
        for item in items
        if item["type"] == "text"
    ]


if __name__ == "__main__":

    raw_items = get_board_items()
    items = parse_items(raw_items)

    groups = group_sticky_notes(items)

    print("\n========== STICKY NOTE GROUPS ==========\n")

    for parent_id, notes in groups.items():

        print(f"PARENT: {parent_id}")
        print(f"STICKIES: {len(notes)}")

        for note in notes:
            print(f"  - {note['text']}")

        print("-" * 50)

    print("\n========== BOARD TEXT ==========\n")

    text_items = find_text_items(items)

    for item in text_items:

        print(f"ID: {item['id']}")
        print(f"TEXT: {item['text']}")
        print(f"PARENT: {item['parent_id']}")
        print("-" * 50)