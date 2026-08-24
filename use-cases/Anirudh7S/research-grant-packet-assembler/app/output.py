import json
from pathlib import Path
from typing import Any, Dict


def save_grant_package(
    grant_package: Dict[str, Any],
    output_path: str | Path,
) -> Path:
    """Save the assembled grant package as formatted JSON."""

    output_path = Path(output_path)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            grant_package,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return output_path