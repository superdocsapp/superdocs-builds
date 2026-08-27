"""Generate the add-on's Prompts.gs from the Python prompts.

There are two implementations of this pipeline — the Python package and the Apps Script
add-on — and the prompts are the part most likely to drift, because they are long prose
that gets tweaked. Drift would mean the tested path and the shipped path no longer ask
the same question.

So the Python constants are the single source and this writes the JavaScript. A test
(`tests/test_prompt_sync.py`) fails if the generated file is out of date, which turns
"remember to update both" into something the suite checks.

    uv run python scripts/sync_prompts.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from thread_to_letter.extract import PROMPT as EXTRACT  # noqa: E402
from thread_to_letter.letter import LETTER, MEMO, NOTHING_PROMPT, PROMPT as LETTER_PROMPT, _SHAPE  # noqa: E402

TARGET = ROOT / "gmail-addon" / "Prompts.gs"

HEADER = """\
/**
 * Prompts, shared with the Python package.
 *
 * GENERATED — do not edit by hand. Run `uv run python scripts/sync_prompts.py`.
 * `tests/test_prompt_sync.py` fails if this file drifts from the Python source, so the
 * tested path and the shipped path always ask the same question.
 */

"""


def _js(name: str, value: str) -> str:
    return f"var {name} = {json.dumps(value)};\n\n"


def render() -> str:
    # The add-on always writes a letter; shape selection is the CLI's job.
    letter_prompt = (
        LETTER_PROMPT
        .replace("{shape}", _SHAPE[LETTER])
        .replace("{participants}", "the people on this thread")
        .replace("{today}", "[DATE]")
    )
    nothing_prompt = (
        NOTHING_PROMPT
        .replace("{shape}", _SHAPE[LETTER])
        .replace("{participants}", "the people on this thread")
        .replace("{today}", "[DATE]")
    )
    return (
        HEADER
        + _js("EXTRACT_PROMPT", EXTRACT)
        + _js("LETTER_PROMPT", letter_prompt)
        + _js("NOTHING_PROMPT", nothing_prompt)
    )


def main() -> int:
    text = render()
    current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
    if current == text:
        print(f"{TARGET.relative_to(ROOT)} is up to date")
        return 0
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
