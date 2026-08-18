import argparse
import json
from pathlib import Path

from backend.superdocs_client import SuperDocsClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Export an approved press kit as DOCX.")
    parser.add_argument("--checkpoint", default="output/emberfall_approval_checkpoint.json")
    parser.add_argument("--review-response", default="output/emberfall_review_response.json")
    parser.add_argument("--output", default="output/emberfall_press_kit.docx")
    parser.add_argument("--filename", default="emberfall_press_kit.docx")
    args = parser.parse_args()

    checkpoint = json.loads(Path(args.checkpoint).read_text(encoding="utf-8"))
    if checkpoint.get("workflow_status") != "approved":
        raise RuntimeError(
            "Export blocked: the human approval gate has not been completed. "
            f"Current status: {checkpoint.get('workflow_status')}"
        )

    review_result = json.loads(Path(args.review_response).read_text(encoding="utf-8"))
    changes = review_result.get("document_changes", {})
    final_html = checkpoint.get("updated_html") or changes.get("updated_html")
    if not final_html:
        raise RuntimeError("No approved HTML is available for export.")

    result = SuperDocsClient().export(
        session_id=review_result["session_id"],
        html=final_html,
        filename=args.filename,
        source_filename=Path(args.filename).with_suffix(".html").name,
        format="docx",
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(result.get("content"), bytes):
        output_path.write_bytes(result["content"])
        print(f"Export successful: {output_path} ({output_path.stat().st_size} bytes)")
        return

    response_path = output_path.with_name(output_path.stem + "_export_response.json")
    response_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Export returned JSON; saved response to {response_path}")


if __name__ == "__main__":
    main()
