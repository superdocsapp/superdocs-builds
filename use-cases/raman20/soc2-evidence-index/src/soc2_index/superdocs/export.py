from __future__ import annotations

import base64
import json
from pathlib import Path

from soc2_index.superdocs.client import Client
from soc2_index.logutil import JsonlLogger

WATERMARK = "SYNTHETIC / NOT AN ATTESTATION"


def parse_export_warnings(headers: dict[str, str]) -> list:
    raw = headers.get("x-export-warnings")
    if not raw:
        return []
    try:
        decoded = base64.b64decode(raw)
        obj = json.loads(decoded)
        return obj if isinstance(obj, list) else []
    except Exception:
        return [{"raw": raw}]


def export_pair(
    client: Client,
    session_id: str,
    dest_dir: Path,
    logger: JsonlLogger | None = None,
) -> tuple[Path, Path, list]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    warnings: list = []
    docx_path = dest_dir / "index.docx"
    pdf_path = dest_dir / "index.pdf"
    body, hdrs = client.export(
        session_id,
        "docx",
        {"filename": "index", "paper_size": "Letter", "orientation": "landscape"},
    )
    warnings.extend(parse_export_warnings(hdrs))
    docx_path.write_bytes(body)
    body, hdrs = client.export(
        session_id,
        "pdf",
        {
            "filename": "index",
            "paper_size": "Letter",
            "orientation": "landscape",
            "watermark_text": WATERMARK,
        },
    )
    warnings.extend(parse_export_warnings(hdrs))
    pdf_path.write_bytes(body)
    if logger:
        for w in warnings:
            logger.log("export_warning", warning=w)
    return docx_path, pdf_path, warnings
