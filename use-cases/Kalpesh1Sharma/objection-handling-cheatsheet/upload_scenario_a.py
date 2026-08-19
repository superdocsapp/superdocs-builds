from __future__ import annotations

import json
import uuid
from pathlib import Path

from superdocs.client import (
    SuperDocsClient,
)


INPUT_PATH = Path(
    "sample_documents"
) / "scenario_a" / "messy_objection_notes.docx"


def main() -> None:
    session_id = (
        "objection-cheatsheet-a-"
        + uuid.uuid4().hex[:8]
    )

    print(
        f"Session: {session_id}"
    )

    print(
        f"Uploading: {INPUT_PATH.name}"
    )

    client = SuperDocsClient()

    result = client.upload_document(
        path=INPUT_PATH,
        session_id=session_id,
        open_mode="replace",
    )

    fixture_path = (
    Path("tests")
    / "fixtures"
    / "scenario_a_superdocs.html"
    )

    fixture_path.parent.mkdir(
    parents=True,
    exist_ok=True,
    )

    fixture_path.write_text(
    result["html"],
    encoding="utf-8",
    )

    print(
    f"Saved HTML fixture: {fixture_path}"
    )

    print()
    print("Upload succeeded.")
    print()

    print(
        "Top-level response keys:"
    )

    for key in result.keys():
        print(
            f"  - {key}"
        )

    print()
    print(
        "Response preview:"
    )

    safe_preview = {}

    for key, value in result.items():
        if isinstance(
            value,
            str,
        ) and len(value) > 1000:
            safe_preview[key] = (
                value[:1000]
                + "... [truncated]"
            )
        else:
            safe_preview[key] = value

    print(
        json.dumps(
            safe_preview,
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()