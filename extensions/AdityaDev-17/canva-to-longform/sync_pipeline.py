"""
sync_pipeline.py — "designs stay linked": checks whether a Canva
design's copy has changed since the last check, and if so, pushes a
targeted update to every SuperDocs session already generated for that
design (one per document type) rather than regenerating from scratch.
"""
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from canva_pipeline import pull_design_assets
from extract_content import extract_text
from superdocs_pipeline import generate_plain
from design_links import get_link, update_link


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_and_sync(access_token: str, superdocs_key: str, design_id: str,
                    sessions: dict, output_dir: Path) -> dict:
    """sessions: {doc_type: session_id} for documents already generated
    for this design. Returns a result dict describing what happened."""
    assets = pull_design_assets(access_token, design_id, output_dir)
    if not assets.get("pdf_path"):
        return {"status": "error", "message": "Could not pull the design from Canva to check for changes."}

    current_text = extract_text(assets["pdf_path"])
    current_hash = content_hash(current_text)

    link = get_link(design_id)
    now = datetime.now(timezone.utc).isoformat()

    if link is None:
        update_link(design_id, "multi", current_hash, current_text, now)
        return {
            "status": "baseline_registered",
            "message": "No prior sync found. Baseline registered — future checks will compare against this.",
        }

    if current_hash == link["last_content_hash"]:
        return {
            "status": "no_changes",
            "message": f"No changes detected since last check ({link['last_synced_at']}).",
        }

    updates = []
    for doc_type, session_id in sessions.items():
        instruction = (
            f"The source design has been updated. Here is the new, current copy:\n\n{current_text}\n\n"
            "Update ONLY the parts of the existing document that reflect outdated information. "
            "Do not regenerate or restructure sections that are still accurate."
        )
        result = generate_plain(superdocs_key, session_id, instruction)
        updates.append({"doc_type": doc_type, "ai_response": result.get("response", "")})

    update_link(design_id, "multi", current_hash, current_text, now)

    return {
        "status": "changed",
        "message": f"Change detected. {len(updates)} document(s) updated.",
        "old_text": link.get("last_text_snapshot", ""),
        "new_text": current_text,
        "updates": updates,
    }