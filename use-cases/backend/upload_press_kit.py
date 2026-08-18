import argparse
import json
from pathlib import Path

from backend.superdocs_client import SuperDocsClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload a rendered press kit to SuperDocs.")
    parser.add_argument("--input", default="output/emberfall_press_kit.html")
    parser.add_argument("--output", default="output/emberfall_upload_response.json")
    parser.add_argument("--session-id", default="emberfall-final")
    args = parser.parse_args()

    result = SuperDocsClient().upload(
        file_path=args.input,
        session_id=args.session_id,
        return_html=True,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Upload successful. Saved response to: {output}")


if __name__ == "__main__":
    main()
