
from pathlib import Path
from html import escape
import base64
import mimetypes
import os

import requests
from dotenv import load_dotenv


load_dotenv()


OUTPUT_DIR = Path("output")
IMAGE_DIR = OUTPUT_DIR / "images"



def download_miro_image(image_url, image_id):
    """
    Download a Miro image using the authenticated
    Miro access token.

    Miro image resource URLs may return JSON metadata
    containing the actual download URL, so we handle
    both JSON and direct image responses.
    """

    token = os.getenv(
        "MIRO_ACCESS_TOKEN"
    )

    if not token:
        print(
            "WARNING: MIRO_ACCESS_TOKEN is missing."
        )
        return None

    IMAGE_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    headers = {
        "Authorization": f"Bearer {token}"
    }

    try:

        response = requests.get(
            image_url,
            headers=headers,
            timeout=30
        )

        if not response.ok:

            print(
                f"WARNING: Failed to fetch image "
                f"{image_id}: "
                f"{response.status_code} "
                f"{response.text[:300]}"
            )

            return None

        content_type = response.headers.get(
            "Content-Type",
            ""
        ).lower()

        # -------------------------------------------------
        # CASE 1: Miro returned image bytes directly
        # -------------------------------------------------

        if content_type.startswith("image/"):

            extension = (
                mimetypes.guess_extension(
                    content_type.split(";")[0]
                )
                or ".png"
            )

            image_file = (
                IMAGE_DIR /
                f"{image_id}{extension}"
            )

            image_file.write_bytes(
                response.content
            )

            print(
                f"Downloaded image: {image_file}"
            )

            return image_file

        # -------------------------------------------------
        # CASE 2: Miro returned JSON metadata
        # -------------------------------------------------

        if "json" in content_type:

            data = response.json()

            print(
                f"DEBUG: image metadata: {data}"
            )

            # Try common URL fields
            actual_url = (
                data.get("url")
                or data.get("download_url")
                or data.get("downloadUrl")
                or data.get("image_url")
                or data.get("imageUrl")
            )

            # Check nested image object
            if not actual_url:

                image_data = data.get(
                    "image"
                )

                if isinstance(
                    image_data,
                    dict
                ):

                    actual_url = (
                        image_data.get("url")
                        or image_data.get(
                            "download_url"
                        )
                        or image_data.get(
                            "downloadUrl"
                        )
                    )

            if not actual_url:

                print(
                    "WARNING: Could not find "
                    "actual image URL in Miro "
                    "metadata."
                )

                return None

            print(
                f"DEBUG: resolved image URL: "
                f"{actual_url}"
            )

            # Download actual image
            image_response = requests.get(
                actual_url,
                headers=headers,
                timeout=30
            )

            if not image_response.ok:

                print(
                    f"WARNING: Failed to download "
                    f"resolved image: "
                    f"{image_response.status_code}"
                )

                return None

            actual_content_type = (
                image_response.headers.get(
                    "Content-Type",
                    "image/png"
                )
                .split(";")[0]
                .lower()
            )

            extension = (
                mimetypes.guess_extension(
                    actual_content_type
                )
                or ".png"
            )

            image_file = (
                IMAGE_DIR /
                f"{image_id}{extension}"
            )

            image_file.write_bytes(
                image_response.content
            )

            print(
                f"Downloaded image: {image_file}"
            )

            return image_file

        # -------------------------------------------------
        # Unknown response
        # -------------------------------------------------

        print(
            f"WARNING: Unexpected Miro response "
            f"Content-Type: {content_type}"
        )

        return None

    except Exception as error:

        print(
            f"WARNING: Could not download "
            f"Miro image {image_id}: "
            f"{error}"
        )

        return None


def image_to_data_uri(image_file):
    """
    Convert a local image into a base64 data URI.

    This makes the generated HTML standalone.
    """

    if not image_file:
        return None

    if not image_file.exists():
        return None

    mime_type, _ = mimetypes.guess_type(
        str(image_file)
    )

    if not mime_type:
        mime_type = "image/png"

    encoded = base64.b64encode(
        image_file.read_bytes()
    ).decode("ascii")

    return (
        f"data:{mime_type};base64,"
        f"{encoded}"
    )


def render_html(document):
    """
    Convert the structured Miro document into
    a styled standalone HTML document.

    Miro images are downloaded using the API token
    and embedded directly into the HTML as base64.
    """

    sections = []

    for section in document:

        items = []

        for item in section["items"]:

            text = escape(
                item["text"]
            )

            source_id = escape(
                str(item["source_id"])
            )

            votes = item.get(
                "votes",
                0
            )

            vote_html = ""

            if votes > 0:

                vote_html = (
                    f'<span class="votes">'
                    f'{votes} votes'
                    f'</span>'
                )

            items.append(
                f"""
                <li class="item">

                    <div class="item-text">
                        {text}
                        {vote_html}
                    </div>

                    <div class="source">
                        Source: Miro sticky note
                        <code>{source_id}</code>
                    </div>

                </li>
                """
            )

        # -------------------------------------------------
        # IMAGES
        # -------------------------------------------------

        images = []

        for image in section.get(
            "images",
            []
        ):

            image_id = image[
                "source_id"
            ]

            image_url = image[
                "url"
            ]

            # Download authenticated Miro image
            image_file = download_miro_image(
                image_url,
                image_id
            )

            # Convert image to embedded base64
            data_uri = image_to_data_uri(
                image_file
            )

            if not data_uri:

                continue

            safe_image_id = escape(
                str(image_id)
            )

            images.append(
                f"""
                <div class="image-card">

                    <img
                        src="{data_uri}"
                        alt="Miro board image"
                    >

                    <div class="image-source">
                        Source: Miro image
                        <code>{safe_image_id}</code>
                    </div>

                </div>
                """
            )

        images_html = ""

        if images:

            images_html = f"""
            <div class="images">

                <h3>Board Images</h3>

                {"".join(images)}

            </div>
            """

        section_title = escape(
            section["title"]
        )

        sections.append(
            f"""
            <section class="section">

                <h2>
                    {section_title}
                </h2>

                {images_html}

                <ul>
                    {"".join(items)}
                </ul>

            </section>
            """
        )

    return f"""<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>Miro Workshop Summary</title>

<style>

* {{
    box-sizing: border-box;
}}

body {{
    margin: 0;
    padding: 40px;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;

    background: #f5f7fb;

    color: #1f2937;
}}

.container {{
    max-width: 900px;
    margin: auto;
}}

.header {{
    background: white;

    padding: 36px;

    border-radius: 16px;

    margin-bottom: 24px;

    box-shadow:
        0 4px 18px
        rgba(0, 0, 0, 0.06);
}}

.header h1 {{
    margin: 0 0 10px;

    font-size: 32px;
}}

.header p {{
    margin: 0;

    color: #6b7280;
}}

.section {{
    background: white;

    padding: 28px;

    margin-bottom: 20px;

    border-radius: 14px;

    box-shadow:
        0 3px 14px
        rgba(0, 0, 0, 0.05);
}}

.section h2 {{
    margin-top: 0;

    font-size: 22px;
}}

ul {{
    padding: 0;

    list-style: none;
}}

.item {{
    padding: 16px;

    margin-bottom: 12px;

    background: #f8fafc;

    border-radius: 10px;

    border-left:
        4px solid #6366f1;
}}

.item-text {{
    font-size: 16px;

    font-weight: 500;
}}

.source {{
    margin-top: 7px;

    font-size: 12px;

    color: #6b7280;
}}

code {{
    background: #eef2ff;

    padding: 2px 6px;

    border-radius: 4px;

    font-family: monospace;
}}

.votes {{
    display: inline-block;

    margin-left: 8px;

    padding: 3px 8px;

    border-radius: 999px;

    background: #e0e7ff;

    font-size: 12px;

    font-weight: 600;
}}

.images {{
    margin-bottom: 24px;
}}

.images h3 {{
    margin-bottom: 14px;

    font-size: 17px;
}}

.image-card {{
    margin-bottom: 18px;

    padding: 12px;

    background: #f8fafc;

    border-radius: 12px;
}}

.image-card img {{
    display: block;

    width: 100%;

    max-height: 500px;

    object-fit: contain;

    border-radius: 8px;

    background: white;
}}

.image-source {{
    margin-top: 8px;

    font-size: 12px;

    color: #6b7280;
}}

.footer {{
    text-align: center;

    color: #9ca3af;

    font-size: 12px;

    margin-top: 30px;
}}

</style>

</head>

<body>

<div class="container">

<header class="header">

<h1>Miro Workshop Summary</h1>

<p>
Automatically generated from the Miro board.
</p>

</header>

{"".join(sections)}

<div class="footer">

Generated by the SuperDocs Miro-to-Document extension.

</div>

</div>

</body>

</html>
"""


def save_html(document):

    OUTPUT_DIR.mkdir(
        exist_ok=True
    )

    html_file = (
        OUTPUT_DIR /
        "miro_document.html"
    )

    html = render_html(
        document
    )

    html_file.write_text(
        html,
        encoding="utf-8"
    )

    return html_file

