from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

STORAGE_DIR = Path("storage/reports")
MAX_PHOTOS = 10
MAX_PHOTO_SIZE = 10 * 1024 * 1024  # 10 MB

ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}


def _safe_filename(filename: str) -> str:
    """
    Keep only a safe filename and remove path traversal characters.
    """
    name = Path(filename).name
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)

    if not name:
        name = "photo"

    return name


async def create_report(
    notes: str | None,
    photos: list[UploadFile],
    project: str | None = None,
) -> dict:
    notes = notes.strip() if notes else None
    project = project.strip() if project and project.strip() else None

    if not notes and not photos:
        raise ValueError("Provide field notes, at least one photo, or both.")

    if len(photos) > MAX_PHOTOS:
        raise ValueError(f"A maximum of {MAX_PHOTOS} photos is allowed.")

    report_id = str(uuid4())
    report_dir = STORAGE_DIR / report_id
    report_dir.mkdir(parents=True, exist_ok=False)

    saved_photos = []

    try:
        if notes:
            notes_path = report_dir / "notes.txt"
            notes_path.write_text(notes, encoding="utf-8")

        for index, photo in enumerate(photos, start=1):
            if photo.content_type not in ALLOWED_IMAGE_TYPES:
                raise ValueError(
                    f"Unsupported photo type: {photo.content_type}. "
                    "Allowed types are JPEG, PNG and WebP."
                )

            contents = await photo.read()

            if len(contents) > MAX_PHOTO_SIZE:
                raise ValueError(
                    f"Photo '{photo.filename}' exceeds the 10 MB size limit."
                )

            filename = f"{index:02d}_{_safe_filename(photo.filename or 'photo')}"
            photo_path = report_dir / filename
            photo_path.write_bytes(contents)

            saved_photos.append(filename)

        metadata = {
            "report_id": report_id,
            "has_notes": bool(notes),
            "photo_count": len(saved_photos),
            "photos": saved_photos,
            "status": "pending",
            # Explicit project passed at submission time (e.g. from a
            # dropdown). May be overwritten/reconciled once extraction
            # runs — see report_pipeline.process_report.
            "project": project,
            "report_date": None,
            "project_mismatch": None,
            "failure_reason": None,
        }

        metadata_path = report_dir / "metadata.json"
        metadata_path.write_text(
            json.dumps(metadata, indent=2),
            encoding="utf-8",
        )

        return {
    **metadata,
    "report_dir": str(report_dir),
}

    except Exception:
        # Do not leave behind a partially created report.
        import shutil

        shutil.rmtree(report_dir, ignore_errors=True)
        raise