"""Dump the test-suite's broken documents to disk for hands-on testing.

The fixtures are the *same* ones the automated suite uses — `tests/broken.py`
is the single source of truth, so a file a human tests by hand is byte-for-byte
the file pytest tests. Run from the build root:

    python3 manual-test/make_fixtures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests import broken  # noqa: E402

OUT = Path(__file__).resolve().parent / "fixtures"

# (filename, generator). The names are what a tester reads in a download
# folder, so they say what the file is for, not what function made it.
FIXTURES = [
    ("00-healthy.docx", broken.healthy),
    ("01-truncated-download.docx", broken.truncated_container),
    ("02-missing-content-types.docx", broken.missing_content_types),
    ("03-unclosed-tags.docx", broken.unclosed_tags),
    ("04-bad-characters.docx", broken.bare_ampersand_and_control_chars),
    ("05-missing-document-part-SHOULD-FAIL.docx", broken.missing_document_part),
    ("06-not-a-word-file-SHOULD-FAIL.docx", broken.not_a_zip_at_all),
    ("07-empty-body-SHOULD-FAIL.docx", broken.empty_body),
]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, make in FIXTURES:
        data = make()
        (OUT / name).write_bytes(data)
        print(f"{name:46} {len(data):>7,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
