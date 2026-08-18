
import os
import re

import requests
from dotenv import load_dotenv


load_dotenv()


def clean_html(html: str) -> str:
    """Convert Miro's HTML content into readable plain text."""

    if not html:
        return ""

    html = html.replace("<br />", " ")
    html = html.replace("<br>", " ")
    html = html.replace("</p>", " ")
    html = html.replace("</li>", " ")

    text = re.sub(r"<[^>]+>", "", html)

    text = text.replace("&nbsp;", " ")
    text = text.replace("&#x1f7e6;", "🟦")
    text = text.replace("&#x1f7e9;", "🟩")
    text = text.replace("&#x1f7e8;", "🟨")
    text = text.replace("&#x1f4c4;", "📄")

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def get_board_items():
    """Fetch all items from the configured Miro board."""

    token = os.getenv("MIRO_ACCESS_TOKEN")
    board_id = os.getenv("MIRO_BOARD_ID")

    if not token:
        raise RuntimeError(
            "MIRO_ACCESS_TOKEN is missing"
        )

    if not board_id:
        raise RuntimeError(
            "MIRO_BOARD_ID is missing"
        )

    url = (
        f"https://api.miro.com/v2/boards/"
        f"{board_id}/items"
    )

    headers = {
        "Authorization": f"Bearer {token}"
    }

    all_items = []

    params = {
        "limit": 50
    }

    while True:

        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=30
        )

        if not response.ok:
            raise RuntimeError(
                f"Miro API request failed: "
                f"{response.status_code} - "
                f"{response.text}"
            )

        data = response.json()

        items = data.get("data", [])

        all_items.extend(items)

        next_cursor = data.get("cursor")

        if not next_cursor:
            break

        params["cursor"] = next_cursor

    print(
        f"DEBUG: fetched {len(all_items)} items from Miro"
    )

    return all_items


def extract_votes(item):
    """
    Extract vote/reaction information when available.

    Miro may expose interaction data differently
    depending on item type and API response.
    """

    votes = 0

    # Direct vote count
    if isinstance(item.get("votes"), int):
        votes = item["votes"]

    # Some responses may expose reaction information
    reactions = item.get("reactions")

    if isinstance(reactions, list):
        votes += len(reactions)

    elif isinstance(reactions, dict):

        for value in reactions.values():

            if isinstance(value, int):
                votes += value

            elif isinstance(value, list):
                votes += len(value)

    return votes


def extract_image_url(item):
    """
    Extract an image URL when the Miro item contains one.
    """

    item_data = item.get("data", {})

    # Direct image URL
    if item_data.get("imageUrl"):
        return item_data["imageUrl"]

    if item_data.get("image_url"):
        return item_data["image_url"]

    # Common nested image structure
    image = item_data.get("image")

    if isinstance(image, dict):

        if image.get("url"):
            return image["url"]

        if image.get("imageUrl"):
            return image["imageUrl"]

    return None


def parse_items(items):
    """
    Convert raw Miro items into a structured representation.

    The parser preserves vote and image information when
    provided by the Miro API.
    """

    parsed = []

    for item in items:

        item_type = item.get("type")
        item_id = item.get("id")

        item_data = item.get(
            "data",
            {}
        )

        content = clean_html(
            item_data.get(
                "content",
                ""
            )
        )

        title = item_data.get(
            "title"
        )

        parent = item.get(
            "parent"
        )

        parent_id = None

        if parent:
            parent_id = parent.get(
                "id"
            )

        votes = extract_votes(
            item
        )

        image_url = extract_image_url(
            item
        )

        parsed.append({
            "id": item_id,
            "type": item_type,
            "text": content,
            "title": title,
            "parent_id": parent_id,
            "votes": votes,
            "image_url": image_url,
        })

    return parsed


def get_items_for_frame(
    items,
    frame_id
):
    """
    Filter parsed Miro items to a selected frame
    and its direct children.
    """

    selected = []

    for item in items:

        if item["id"] == frame_id:

            selected.append(
                item
            )

            continue

        if item.get(
            "parent_id"
        ) == frame_id:

            selected.append(
                item
            )

    return selected


def print_structure(items):
    """Display the board structure."""

    print(
        "\n========== MIRO BOARD STRUCTURE ==========\n"
    )

    for item in items:

        print(
            f"TYPE: {item['type']}"
        )

        print(
            f"ID: {item['id']}"
        )

        if item["title"]:

            print(
                f"TITLE: {item['title']}"
            )

        if item["text"]:

            print(
                f"TEXT: {item['text']}"
            )

        if item["parent_id"]:

            print(
                f"PARENT: {item['parent_id']}"
            )

        print(
            f"VOTES: {item['votes']}"
        )

        if item["image_url"]:

            print(
                f"IMAGE: {item['image_url']}"
            )

        print(
            "-" * 50
        )


if __name__ == "__main__":

    items = get_board_items()

    parsed = parse_items(
        items
    )

    print(
        f"Fetched {len(parsed)} Miro items."
    )

    print_structure(
        parsed
    )

