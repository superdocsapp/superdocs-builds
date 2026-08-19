from __future__ import annotations

from pathlib import Path

from core.cheatsheet import (
    build_cheatsheet_markdown,
    build_coverage_summary,
)
from core.docx_render import (
    build_cheatsheet_docx_bytes,
)
from core.html_input import (
    extract_lines_from_superdocs_html,
)
from core.parser import (
    parse_objection_notes,
)


HTML_FIXTURE = (
    Path("tests")
    / "fixtures"
    / "scenario_a_superdocs.html"
)

OUTPUT_DIR = Path(
    "outputs"
)


def main() -> None:
    html = HTML_FIXTURE.read_text(
        encoding="utf-8"
    )

    lines = (
        extract_lines_from_superdocs_html(
            html
        )
    )

    result = parse_objection_notes(
        lines
    )

    summary = build_coverage_summary(
        result
    )

    if not summary["coverage_passed"]:
        raise RuntimeError(
            "Coverage validation failed. "
            "Outputs were not generated."
        )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    markdown_path = (
        OUTPUT_DIR
        / "scenario_a_objection_cheatsheet.md"
    )

    docx_path = (
        OUTPUT_DIR
        / "scenario_a_objection_cheatsheet.docx"
    )

    markdown_path.write_text(
        build_cheatsheet_markdown(
            result
        ),
        encoding="utf-8",
    )

    docx_path.write_bytes(
        build_cheatsheet_docx_bytes(
            result
        )
    )

    print("Coverage:")
    print(
        f"  Detected objections: "
        f"{summary['detected_objections']}"
    )
    print(
        f"  Output blocks: "
        f"{summary['output_blocks']}"
    )
    print(
        f"  Complete responses: "
        f"{summary['complete_responses']}"
    )
    print(
        f"  Missing responses: "
        f"{summary['missing_responses']}"
    )
    print(
        f"  Dropped objections: "
        f"{summary['dropped_objections']}"
    )
    print(
        f"  Duplicate assignments: "
        f"{summary['duplicate_assignments']}"
    )

    print()
    print("Generated:")
    print(
        f"  {markdown_path}"
    )
    print(
        f"  {docx_path}"
    )


if __name__ == "__main__":
    main()