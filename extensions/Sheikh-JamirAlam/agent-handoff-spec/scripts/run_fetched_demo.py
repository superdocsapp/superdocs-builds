"""Run the SuperDocs-backed fetched-document demonstration."""

import json
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo.run_demo import run_fetched_demo  # noqa: E402


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing {name} in .env")
    return value


def as_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def extract_sections(html: str) -> dict[str, str]:
    """Extract the configured heading sections from simple SuperDocs HTML."""
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


load_dotenv()
document_id = required("SUPERDOCS_DOCUMENT_ID")
api_key = required("SUPERDOCS_API_KEY")
write_back = as_bool("SUPERDOCS_WRITE_BACK", True)
session_id = os.getenv("SUPERDOCS_SESSION_ID") or None
export_format = os.getenv("SUPERDOCS_EXPORT_FORMAT", "docx") or None
export_path = os.getenv("SUPERDOCS_EXPORT_PATH", "exports/fetched-demo.pdf")
spelling_sections = [s.strip() for s in required(
    "SPELLING_SECTIONS").split(",") if s.strip()]
math_section = required("MATH_SECTION")
verbose = as_bool("SUPERDOCS_VERBOSE", False)
print(f"[Demo] use_gemini={as_bool('USE_GEMINI', True)} write_back={write_back} approval_mode={os.getenv('SUPERDOCS_APPROVAL_MODE', 'approve_all')}")

try:
    result = run_fetched_demo(
        document_id=document_id,
        api_key=api_key,
        section_extractor=extract_sections,
        log_path=os.getenv("DEMO_LOG_PATH", "logs/fetched-demo.json"),
        use_gemini=as_bool("USE_GEMINI", True),
        session_id=session_id,
        write_back=write_back,
        approval_mode=os.getenv("SUPERDOCS_APPROVAL_MODE", "approve_all"),
        export_format=export_format if write_back else None,
        spelling_sections=spelling_sections,
        math_section=math_section,
        verbose=verbose,
        export_path=export_path,
    )
except Exception as error:
    print(f"ERROR: {error}", file=sys.stderr)
    if hasattr(error, "detail") and isinstance(error.detail, dict):
        print(json.dumps(error.detail, indent=2), file=sys.stderr)
    raise SystemExit(1)

print(f"accepted={result.accepted}")
print(
    f"validations={[validation.accepted for validation in result.validations]}")
print(f"trace_entries={len(result.trace)}")
if hasattr(result, "export"):
    print(f"export={json.dumps(result.export)}")
