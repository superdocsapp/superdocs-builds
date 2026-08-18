
from pathlib import Path
import hashlib
import json
import sys

from document_builder import build_document_structure

from html_exporter import save_html

from miro_parser import (
    get_board_items,
    parse_items,
    get_items_for_frame,
)


OUTPUT_DIR = Path("output")

OUTPUT_FILE = (
    OUTPUT_DIR /
    "miro_document.md"
)

CACHE_FILE = (
    OUTPUT_DIR /
    ".section_cache.json"
)


def clean_text(text):
    """
    Clean formatting artifacts from Miro text.
    """

    if not text:
        return ""

    text = text.strip()

    # Remove accidental trailing 'n'
    if text.endswith("n") and not text.endswith(" in"):
        text = text[:-1].rstrip()

    # Normalize whitespace
    text = " ".join(
        text.split()
    )

    return text


def section_fingerprint(section):
    """
    Create a stable fingerprint for a section.

    The fingerprint is based on:

    - Miro frame ID
    - section title
    - source item IDs
    - source item text
    """

    source_items = []

    for item in section["items"]:

        source_items.append(
            {
                "source_id": item["source_id"],
                "text": clean_text(
                    item["text"]
                ),
            }
        )

    payload = {
        "frame_id": section["id"],
        "title": section["title"],
        "items": source_items,
    }

    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
    )

    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()


def render_section(section):
    """
    Convert one structured section
    into Markdown.
    """

    lines = []

    lines.append(
        f"## {section['title']}"
    )

    lines.append("")

    for item in section["items"]:

        text = clean_text(
            item["text"]
        )

        source_id = item["source_id"]

        lines.append(
            f"- {text}"
        )

        lines.append(
            "  - Source: Miro sticky note "
            f"`{source_id}`"
        )

        # Include votes only when available
        votes = item.get(
            "votes",
            0
        )

        if votes > 0:

            lines.append(
                f"  - Votes: {votes}"
            )

    lines.append("")

    return "\n".join(lines)


def load_cache():
    """
    Load the previous section cache.

    If the cache does not exist,
    return an empty dictionary.
    """

    if not CACHE_FILE.exists():
        return {}

    try:

        return json.loads(
            CACHE_FILE.read_text(
                encoding="utf-8"
            )
        )

    except (
        json.JSONDecodeError,
        OSError,
    ):

        print(
            "WARNING: Could not read "
            "section cache."
        )

        return {}


def save_cache(cache):
    """
    Save the section cache.
    """

    OUTPUT_DIR.mkdir(
        exist_ok=True
    )

    CACHE_FILE.write_text(
        json.dumps(
            cache,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def generate_markdown(document):
    """
    Generate the complete Markdown document.

    Unchanged sections are reused
    from the cache.

    Changed sections are rendered again.
    """

    old_cache = load_cache()

    new_cache = {}

    rendered_sections = []

    generated_count = 0
    reused_count = 0

    for section in document:

        frame_id = section["id"]

        fingerprint = section_fingerprint(
            section
        )

        cached = old_cache.get(
            frame_id
        )

        # ---------------------------------------------
        # REUSE UNCHANGED SECTION
        # ---------------------------------------------

        if (
            cached
            and cached.get("fingerprint")
            == fingerprint
            and cached.get("markdown")
        ):

            markdown = cached["markdown"]

            reused_count += 1

            print(
                f"REUSED section: "
                f"{section['title']}"
            )

        # ---------------------------------------------
        # GENERATE NEW / CHANGED SECTION
        # ---------------------------------------------

        else:

            markdown = render_section(
                section
            )

            generated_count += 1

            print(
                f"GENERATED section: "
                f"{section['title']}"
            )

        new_cache[frame_id] = {
            "fingerprint": fingerprint,
            "title": section["title"],
            "markdown": markdown,
        }

        rendered_sections.append(
            markdown
        )

    # ---------------------------------------------
    # Save new cache
    #
    # Sections that disappeared from the board
    # are automatically removed from the cache.
    # ---------------------------------------------

    save_cache(
        new_cache
    )

    lines = []

    lines.append(
        "# Miro Workshop Summary"
    )

    lines.append("")

    lines.append(
        "> Automatically generated from "
        "the Miro board."
    )

    lines.append(
        "> Each item includes its original "
        "Miro source ID."
    )

    lines.append("")

    lines.extend(
        rendered_sections
    )

    markdown = "\n".join(
        lines
    )

    return (
        markdown,
        generated_count,
        reused_count,
    )


def save_document(content):
    """
    Save the generated Markdown document.
    """

    OUTPUT_DIR.mkdir(
        exist_ok=True
    )

    OUTPUT_FILE.write_text(
        content,
        encoding="utf-8"
    )

    return OUTPUT_FILE


def main():

    print(
        "Fetching Miro board..."
    )

    # ---------------------------------------------
    # FETCH BOARD
    # ---------------------------------------------

    raw_items = get_board_items()

    items = parse_items(
        raw_items
    )

    # ---------------------------------------------
    # OPTIONAL FRAME SELECTION
    #
    # Whole board:
    #
    #     python document_generator.py
    #
    # Selected frame:
    #
    #     python document_generator.py FRAME_ID
    # ---------------------------------------------

    frame_id = None

    if len(sys.argv) > 1:

        frame_id = sys.argv[1]

    if frame_id:

        print(
            f"Selected frame: {frame_id}"
        )

        items = get_items_for_frame(
            items,
            frame_id
        )

        if not items:

            raise RuntimeError(
                f"No Miro items found for "
                f"frame: {frame_id}"
            )

    else:

        print(
            "Using entire Miro board."
        )

    # ---------------------------------------------
    # BUILD STRUCTURED DOCUMENT
    # ---------------------------------------------

    document = build_document_structure(
        items
    )

    # ---------------------------------------------
    # GENERATE MARKDOWN
    # ---------------------------------------------

    (
        markdown,
        generated_count,
        reused_count,
    ) = generate_markdown(
        document
    )

    # ---------------------------------------------
    # SAVE MARKDOWN
    # ---------------------------------------------

    output_file = save_document(
        markdown
    )

    # ---------------------------------------------
    # GENERATE HTML
    # ---------------------------------------------

    html_file = save_html(
        document
    )

    # ---------------------------------------------
    # SUCCESS MESSAGE
    # ---------------------------------------------

    print()

    print(
        "Document generated successfully!"
    )

    print(
        f"Markdown output: {output_file}"
    )

    print(
        f"HTML output:    {html_file}"
    )

    print()

    print(
        "========== UPDATE SUMMARY =========="
    )

    print(
        f"Sections generated: {generated_count}"
    )

    print(
        f"Sections reused:    {reused_count}"
    )

    print()

    print(
        "========== GENERATED DOCUMENT =========="
    )

    print()

    print(
        markdown
    )


if __name__ == "__main__":

    main()

