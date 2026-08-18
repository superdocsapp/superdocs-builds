import argparse
import json
from pathlib import Path

from backend.html_renderer import render_press_kit_html
from backend.superdocs_client import SuperDocsClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Render and submit a press kit for SuperDocs review.")
    parser.add_argument("--input", default="output/emberfall_press_kit.json")
    parser.add_argument("--html", default="output/emberfall_press_kit.html")
    parser.add_argument("--output", default="output/emberfall_superdocs_response.json")
    parser.add_argument("--session-id", default="emberfall-press-kit")
    args = parser.parse_args()

    press_kit = json.loads(Path(args.input).read_text(encoding="utf-8"))
    html = render_press_kit_html(press_kit)
    Path(args.html).parent.mkdir(parents=True, exist_ok=True)
    Path(args.html).write_text(html, encoding="utf-8")

    message = """
Review this game press kit for publication readiness.
Preserve all verified factual information and the verbatim quote.
Check that the three descriptions describe the same game at different levels
of detail, and that features, history, awards, coverage, and every asset remain
consistent with the source. Do not invent or alter unsupported facts.
Return proposed improvements only where necessary.
"""
    result = SuperDocsClient().chat(message=message, session_id=args.session_id, document_html=html)
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved SuperDocs response to: {args.output}")


if __name__ == "__main__":
    main()
