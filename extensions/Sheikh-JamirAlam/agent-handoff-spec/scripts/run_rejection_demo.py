"""Run the fetched, local-only rejection demonstration."""

import os

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo.run_demo import run_fetched_rejection_demo  # noqa: E402


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing {name} in .env")
    return value


def extract_sections(html: str) -> dict[str, str]:
    from html.parser import HTMLParser

    wanted = [name.strip() for name in required(
        "DOCUMENT_SECTIONS").split(",") if name.strip()]
    aliases = {name.lower().replace(" ", "-"): name for name in wanted}
    output = {name: "" for name in wanted}
    current = None

    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_row = False
            self.in_cell = False
            self.cell_text = ""
            self.row: list[str] = []

        def handle_starttag(self, tag, attrs):
            nonlocal current
            if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                current = None
            elif tag == "tr":
                self.in_row = True
                self.row = []
            elif tag in {"th", "td"} and self.in_row:
                self.in_cell = True
                self.cell_text = ""

        def handle_endtag(self, tag):
            if tag in {"th", "td"} and self.in_cell:
                self.row.append(" ".join(self.cell_text.split()))
                self.in_cell = False
            elif tag == "tr" and self.in_row:
                if current and self.row:
                    output[current] += " | ".join(self.row) + "\n"
                self.in_row = False

        def handle_data(self, data):
            nonlocal current
            if self.in_cell:
                self.cell_text += data
                return
            text = data.strip()
            normalized = text.lower().replace(" ", "-")
            if normalized in aliases:
                current = aliases[normalized]
            elif current and text:
                output[current] += text + "\n"

    Parser().feed(html)
    return output


result = run_fetched_rejection_demo(
    required("SUPERDOCS_DOCUMENT_ID"),
    required("SUPERDOCS_API_KEY"),
    extract_sections,
    use_gemini=os.getenv("USE_GEMINI", "true").strip().lower() in
    {"1", "true", "yes", "on"},
    spelling_sections=[s.strip() for s in required("SPELLING_SECTIONS").split(",") if s.strip()],
    math_section=required("MATH_SECTION"),
    verbose=os.getenv("SUPERDOCS_VERBOSE", "false").strip().lower() in
    {"1", "true", "yes", "on"},
)
print(f"accepted={result.accepted}")
for index, validation in enumerate(result.validations, start=1):
    print(f"validation_{index}_accepted={validation.accepted}")
    print(f"validation_{index}_reason={validation.reason}")
