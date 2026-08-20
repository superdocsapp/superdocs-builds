import os
import re
import html
import uuid
import time
import warnings
from typing import List, Dict, Any, Optional

warnings.filterwarnings("ignore")

from mcp.server.fastmcp import FastMCP

from .docx_parser import extract_docx_comments
from .docx_writer import apply_edits_and_resolve_comments
from .superdocs_client import SuperDocsClient, SuperDocsAPIError

# Initialize FastMCP Server
mcp = FastMCP("SuperDocs-Word-Comment-Agent")

# In-memory review session state storage (review_id -> context)
REVIEW_CONTEXTS: Dict[str, Dict[str, Any]] = {}
# Tracks the latest review session ID for each comment ID (comment_id -> latest review_id)
LATEST_REVIEW_PER_COMMENT: Dict[str, str] = {}

def get_client() -> SuperDocsClient:
    return SuperDocsClient()

def clean_html_text(html_content: str) -> str:
    """
    Strips HTML tags and unescapes entities to return clean text for Word document replacement.
    """
    if not html_content:
        return ""
    text = re.sub(r'<[^>]+>', '', html_content)
    text = html.unescape(text)
    return text.strip()

@mcp.tool()
def inspect_word_comments(file_path: str) -> Dict[str, Any]:
    """
    Inspects a Word document (.docx) and extracts all unresolved comments,
    comment IDs, instruction text, and exact anchor text ranges.
    """
    return extract_docx_comments(file_path)

@mcp.tool()
def propose_comment_edits(
    file_path: str,
    comment_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Reads unresolved comments, sends scoped edit instructions to SuperDocs API,
    obtains AI proposed changes, and returns a review_id with mapped comment proposals.

    HUMAN-IN-THE-LOOP INSTRUCTION FOR AI CLIENTS:
    After calling this tool, PRESENT the proposed edits to the human user in chat
    and WAIT for their explicit approval or rejection decisions before calling review_comment_changes.
    Do NOT auto-approve proposed edits in code without human input.
    """
    extracted = extract_docx_comments(file_path)
    all_comments = extracted.get("comments", [])

    if not all_comments:
        return {
            "review_id": None,
            "message": "No unresolved comments found in document.",
            "proposals": []
        }

    # Filter to requested comments if specified
    if comment_ids:
        target_comment_ids = set(str(cid) for cid in comment_ids)
        target_comments = [c for c in all_comments if str(c["comment_id"]) in target_comment_ids]
    else:
        target_comments = all_comments

    review_id = f"rev_{uuid.uuid4().hex[:8]}"
    client = get_client()

    comments_map: Dict[str, Dict[str, Any]] = {}
    proposals_list = []

    for c in target_comments:
        cid = str(c["comment_id"])
        instruction = c["instruction"]
        anchor_text = c["anchor_text"]
        no_change = c["no_change_needed"]
        comment_session_id = f"session_{review_id}_{cid}"

        # Track latest review_id for this comment to prevent stale execution
        LATEST_REVIEW_PER_COMMENT[cid] = review_id

        if no_change:
            # Honor "no change needed" without calling AI endpoint
            comment_entry = {
                "comment_id": cid,
                "instruction": instruction,
                "original_anchor": anchor_text,
                "change_id": f"ch_skipped_{cid}",
                "proposed_text": anchor_text,
                "status": "skipped_no_change",
                "job_id": None,
                "session_id": comment_session_id
            }
        else:
            # Upload document to comment-specific session
            client.upload_document(comment_session_id, file_path, os.path.basename(file_path))

            # Send targeted edit instruction
            job_id = client.send_async_edit(comment_session_id, instruction, anchor_text, cid)
            job_res = client.poll_job_status(job_id)
            
            changes = job_res.get("changes", [])
            proposed_text = anchor_text  # Fallback to original if no edit returned
            change_id = f"ch_{cid}"

            if changes:
                first_change = changes[0]
                change_id = first_change.get("change_id", change_id)
                raw_text = first_change.get("new_text") or first_change.get("new_html") or anchor_text
                proposed_text = clean_html_text(raw_text)

            comment_entry = {
                "comment_id": cid,
                "instruction": instruction,
                "original_anchor": anchor_text,
                "change_id": change_id,
                "proposed_text": proposed_text,
                "status": "pending",
                "job_id": job_id,
                "session_id": comment_session_id
            }
            proposals_list.append({
                "comment_id": cid,
                "change_id": change_id,
                "instruction": instruction,
                "original_anchor": anchor_text,
                "proposed_text": proposed_text
            })

        comments_map[cid] = comment_entry

    # Save to in-memory review context
    REVIEW_CONTEXTS[review_id] = {
        "review_id": review_id,
        "file_path": file_path,
        "comments_map": comments_map,
        "created_at": time.time()
    }

    return {
        "review_id": review_id,
        "file_path": file_path,
        "proposals_count": len(proposals_list),
        "proposals": proposals_list
    }

@mcp.tool()
def review_comment_changes(
    review_id: str,
    decisions: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Accepts per-comment approve/reject decisions for a review_id.
    Supports optional override_text to explicitly update proposed text on approval.
    decisions shape: [{"comment_id": "1", "approved": True, "override_text": "Final text"}, ...]
    """
    if review_id not in REVIEW_CONTEXTS:
        raise ValueError(f"Review session ID '{review_id}' not found.")

    ctx = REVIEW_CONTEXTS[review_id]
    comments_map = ctx["comments_map"]
    client = get_client()

    approved_comment_ids = []
    rejected_comment_ids = []

    for d in decisions:
        cid = str(d["comment_id"])
        is_approved = bool(d.get("approved", True))

        if cid in comments_map:
            c_info = comments_map[cid]
            c_info["status"] = "approved" if is_approved else "rejected"
            
            # Support explicit human override text if provided
            if "override_text" in d and d["override_text"] is not None:
                c_info["proposed_text"] = str(d["override_text"])

            if is_approved:
                approved_comment_ids.append(cid)
                c_info["approved_human_text"] = c_info["proposed_text"]
            else:
                rejected_comment_ids.append(cid)

            if c_info["job_id"] and c_info["session_id"]:
                client.approve_changes(
                    c_info["session_id"],
                    c_info["job_id"],
                    [{"change_id": c_info["change_id"], "approved": is_approved}]
                )

    return {
        "review_id": review_id,
        "approved_comments": approved_comment_ids,
        "rejected_comments": rejected_comment_ids,
        "status": "decisions_recorded"
    }

@mcp.tool()
def export_word_document(
    review_id: str,
    output_path: str
) -> Dict[str, Any]:
    """
    Exports final Word document.
    Surgically writes approved edit replacements to target anchor ranges in Word XML
    and sets comment threads to resolved (w:done="1").
    """
    if review_id not in REVIEW_CONTEXTS:
        raise ValueError(f"Review session ID '{review_id}' not found.")

    ctx = REVIEW_CONTEXTS[review_id]
    input_path = ctx["file_path"]
    comments_map = ctx["comments_map"]

    approved_edits = []
    for cid, c_info in comments_map.items():
        if c_info["status"] == "approved":
            # Reject execution if review_id is stale for any comment being exported
            latest_rid = LATEST_REVIEW_PER_COMMENT.get(cid)
            if latest_rid and latest_rid != review_id:
                raise ValueError(
                    f"Stale review session ID '{review_id}' for comment '{cid}'. "
                    f"A newer review session ('{latest_rid}') exists for this comment."
                )
            approved_edits.append({
                "comment_id": cid,
                "replacement_text": c_info["proposed_text"],
                "human_approved_text": c_info.get("approved_human_text", c_info["proposed_text"])
            })

    result = apply_edits_and_resolve_comments(
        input_path=input_path,
        output_path=output_path,
        approved_edits=approved_edits
    )

    return {
        "review_id": review_id,
        "output_path": output_path,
        "applied_edits_count": result["applied_edits_count"],
        "resolved_comments_count": result["resolved_comments_count"],
        "verified": result.get("verified", True),
        "verification_status": result.get("verification_status", "success"),
        "verification_mismatches": result.get("verification_mismatches", [])
    }

if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    port = os.getenv("PORT", "8000")
    host = os.getenv("HOST", "0.0.0.0")
    if transport in ("sse", "http"):
        os.environ["FASTMCP_PORT"] = port
        os.environ["FASTMCP_HOST"] = host
        print(f"Starting SuperDocs Word Comment Agent MCP Server on http://{host}:{port} (SSE Transport)...")
        mcp.run(transport="sse")
    else:
        mcp.run()
