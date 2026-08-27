"""The fixtures Salvage's interface is tested against are captured from real repairs.

Not written by hand. A hand-written fake of this stream would let the interface
pass its tests while showing a person something the engine never says -- which is
the shape of BUG-015, and of BUG-012 and BUG-014 before it.

Regenerate deliberately with:

    SALVAGE_UPDATE_FIXTURES=1 pytest tests/test_frontend_fixtures.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from docrepair.engine import repair
from tests import broken

FIXTURES = Path(__file__).resolve().parents[1] / "frontend" / "src" / "test" / "fixtures"

CASES = [
    ("healthy", "00-healthy.docx", broken.healthy),
    ("truncated", "01-truncated-download.docx", broken.truncated_container),
    ("missing-content-types", "02-missing-content-types.docx", broken.missing_content_types),
    ("unclosed-tags", "03-unclosed-tags.docx", broken.unclosed_tags),
    ("bad-characters", "04-bad-characters.docx", broken.bare_ampersand_and_control_chars),
    ("missing-document-part", "05-missing-document-part.docx", broken.missing_document_part),
    ("not-a-word-file", "06-not-a-word-file.docx", broken.not_a_zip_at_all),
    ("empty-body", "07-empty-body.docx", broken.empty_body),
    ("illustrated", "08-illustrated.docx", broken.illustrated),
    ("truncated-illustrated", "09-truncated-illustrated.docx",
     broken.truncated_illustrated),
]


def _capture(name: str, filename: str, make) -> dict:
    """One repair, recorded exactly as the web endpoint streams it."""
    events: list[dict] = []
    r = repair(make(), filename, on_progress=lambda stage, message: events.append(
        {"stage": stage, "message": message}
    ))
    report = r.as_payload(
        download=f"/api/download/{name}-token" if r.ok else None,
        style=f"/api/style/{name}-token" if r.ok else None,
    )
    # The rebuild is written to a path in the working directory; recording it
    # would make the fixture depend on where the tests were run from.
    report["output_path"] = ""
    return {"name": name, "filename": filename, "events": events, "report": report}


def _dump(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def test_the_interface_fixtures_are_captured_from_real_repairs_and_have_not_drifted():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    update = os.environ.get("SALVAGE_UPDATE_FIXTURES") == "1"
    stale: list[str] = []

    index = []
    for name, filename, make in CASES:
        captured = _capture(name, filename, make)
        index.append({"name": name, "filename": filename, "ok": captured["report"]["ok"]})
        path = FIXTURES / f"{name}.json"
        text = _dump(captured)
        if update or not path.exists():
            path.write_text(text)
            continue
        if path.read_text() != text:
            stale.append(name)

    index_path = FIXTURES / "index.json"
    index_text = _dump(index)
    if update or not index_path.exists():
        index_path.write_text(index_text)
    elif index_path.read_text() != index_text:
        stale.append("index")

    assert not stale, (
        "these interface fixtures no longer match what a real repair produces: "
        + ", ".join(sorted(stale))
        + ". The interface is tested against them, so a drifted fixture is a page "
        "that passes its tests and lies to somebody about their document. "
        "Regenerate with SALVAGE_UPDATE_FIXTURES=1 and read the diff."
    )


@pytest.mark.parametrize("name,_f,_m", CASES)
def test_every_case_was_captured(name: str, _f: str, _m):
    assert (FIXTURES / f"{name}.json").exists(), f"{name} was never captured"
