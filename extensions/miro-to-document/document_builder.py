
from miro_parser import get_board_items, parse_items
from section_detector import detect_section_title


def normalize_text(text):
    """
    Normalize text so we can compare similar sticky notes.
    """

    if not text:
        return ""

    text = text.lower().strip()

    # Remove accidental trailing characters
    text = text.rstrip("n").strip()

    # Normalize whitespace
    text = " ".join(
        text.split()
    )

    return text


def deduplicate_items(items):
    """
    Remove duplicate sticky-note content.

    Duplicate detection is case-insensitive
    and whitespace-insensitive.
    """

    seen = set()

    unique_items = []

    for item in items:

        normalized = normalize_text(
            item["text"]
        )

        if not normalized:
            continue

        if normalized in seen:
            continue

        seen.add(
            normalized
        )

        unique_items.append(
            item
        )

    return unique_items


def build_document_structure(items):
    """
    Build a structured document from Miro frames,
    sticky notes and images.

    Each frame becomes a document section.

    Sticky notes are attached to their parent frame.

    Images are attached to their parent frame.
    """

    # ---------------------------------------------------------
    # STEP 1: Collect frames
    # ---------------------------------------------------------

    frames = {}

    for item in items:

        if item["type"] != "frame":
            continue

        frames[item["id"]] = {
            "id": item["id"],
            "original_title": (
                item["title"]
                or "Untitled Frame"
            ),
            "title": (
                item["title"]
                or "Untitled Frame"
            ),
            "items": [],
            "images": [],
        }

    # ---------------------------------------------------------
    # STEP 2: Attach sticky notes to frames
    # ---------------------------------------------------------

    for item in items:

        if item["type"] != "sticky_note":
            continue

        parent_id = item.get(
            "parent_id"
        )

        if parent_id not in frames:
            continue

        text = item.get(
            "text",
            ""
        ).strip()

        if not text:
            continue

        frames[parent_id]["items"].append(
            {
                "source_id": item["id"],
                "text": text,
                "votes": item.get(
                    "votes",
                    0
                ),
            }
        )

    # ---------------------------------------------------------
    # STEP 3: Attach images to frames
    # ---------------------------------------------------------

    for item in items:

        if item["type"] != "image":
            continue

        parent_id = item.get(
            "parent_id"
        )

        if parent_id not in frames:
            continue

        image_url = item.get(
            "image_url"
        )

        if not image_url:
            continue

        frames[parent_id]["images"].append(
            {
                "source_id": item["id"],
                "url": image_url,
                "votes": item.get(
                    "votes",
                    0
                ),
            }
        )

    # ---------------------------------------------------------
    # STEP 4: Remove duplicate sticky notes
    # ---------------------------------------------------------

    for frame in frames.values():

        frame["items"] = deduplicate_items(
            frame["items"]
        )

    # ---------------------------------------------------------
    # STEP 5: Detect semantic section title
    # ---------------------------------------------------------

    document = []

    for frame in frames.values():

        # A frame can contain an image even if
        # it has no sticky notes.
        #
        # However, for the current workshop document
        # we only create a section when it contains
        # meaningful content.

        if (
            not frame["items"]
            and not frame["images"]
        ):
            continue

        if frame["items"]:

            frame["title"] = detect_section_title(
                frame["items"]
            )

        else:

            frame["title"] = frame[
                "original_title"
            ]

        document.append(
            frame
        )

    # ---------------------------------------------------------
    # STEP 6: Remove duplicate sticky notes
    # across sections
    # ---------------------------------------------------------

    seen_content = set()

    cleaned_document = []

    for section in document:

        unique_items = []

        for item in section["items"]:

            normalized = normalize_text(
                item["text"]
            )

            if normalized in seen_content:
                continue

            seen_content.add(
                normalized
            )

            unique_items.append(
                item
            )

        section["items"] = unique_items

        # Keep section if it contains either:
        # - sticky notes
        # - images

        if (
            section["items"]
            or section["images"]
        ):

            cleaned_document.append(
                section
            )

    return cleaned_document


def print_document(document):

    print(
        "\n========== DOCUMENT STRUCTURE ==========\n"
    )

    for section in document:

        print(
            f"# {section['title']}"
        )

        print(
            f"Frame ID: {section['id']}"
        )

        print(
            "Original Miro Title: "
            f"{section['original_title']}"
        )

        print()

        if section["images"]:

            print(
                "Images:"
            )

            for image in section["images"]:

                print(
                    f"- Image: "
                    f"{image['source_id']}"
                )

                print(
                    f"  URL: "
                    f"{image['url']}"
                )

            print()

        if section["items"]:

            print(
                "Sticky Notes:"
            )

            for item in section["items"]:

                print(
                    f"- {item['text']}"
                )

        print(
            "\n" + "=" * 60
        )


if __name__ == "__main__":

    print(
        "Fetching Miro board..."
    )

    raw_items = get_board_items()

    items = parse_items(
        raw_items
    )

    document = build_document_structure(
        items
    )

    print_document(
        document
    )

