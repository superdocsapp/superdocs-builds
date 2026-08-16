import asyncio
from pathlib import Path

from app.services.superdocs_service import SuperDocsClient


async def main() -> None:
    photo_path = Path(
        r"C:\Users\Dell\OneDrive\Pictures\baboon.jpeg"
    )

    if not photo_path.exists():
        raise FileNotFoundError(photo_path)

    raw_bytes = photo_path.read_bytes()

    import base64
    import mimetypes

    mime_type, _ = mimetypes.guess_type(
        photo_path.name
    )

    attachment = {
        "id": "photo-test-1",
        "name": photo_path.name,
        "base64Data": base64.b64encode(
            raw_bytes
        ).decode("ascii"),
        "mimeType": mime_type,
        "size": len(raw_bytes),
    }

    client = SuperDocsClient()

    result = await client.chat(
        session_id="daily-field-photo-test",
        message="""
Look at the attached construction site photo.

Describe what is visibly present and write a concise
professional caption suitable for a Daily Field Report.

Do not invent facts that are not visible.
""",
        image_attachments=[attachment],
    )

    print(result)


if __name__ == "__main__":
    asyncio.run(main())