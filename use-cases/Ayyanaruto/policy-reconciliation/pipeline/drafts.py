"""Stage 6: SuperDocs HITL merge drafts. Prompt lives here."""

from __future__ import annotations

from pathlib import Path

from .common import client, esc, slug

MERGE_PROMPT = """Write ONE unified HR policy in the currently focused blank document.

Title: {title}
Source A filename: {doc_a}
Source B filename: {doc_b}
Why a merge was recommended: {evidence}

Rules:
- Read the two source policies open in this session and write a single coherent policy, not a concatenation.
- Use clear headings (Purpose, Scope, then the operative rules).
- Where the sources already agree, state the rule once in plain language.
- Where they disagree on a number or threshold, pick a single proposed value and briefly note both source positions in a short 'Reconciliation note' under that clause.
- Do not drop a topic that exists in only one source — carry it forward.
- Do not invent legal advice. This is a draft for human review.
"""


def _open_docs_as_tabs(paths, session_id):
    """Upload local files into a session as tabs (replace, then new_focused)."""
    first = True
    for path in paths:
        mode = "replace" if first else "new_focused"
        first = False
        client.upload(path, session_id, open_mode=mode)


def _draft_html(policy, pending, job):
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Merge draft</title></head><body>",
        f"<h1>{esc(policy.get('title') or 'Merged policy')}</h1>",
        f"<p><strong>Evidence:</strong> {esc(policy.get('evidence') or '')}</p>",
    ]
    if pending:
        parts.append("<h2>Proposed SuperDocs changes (awaiting approval)</h2>")
        for change in pending:
            parts.append(f"<h3>{esc(change.get('operation') or 'edit')} · {esc(change.get('change_id') or '')}</h3>")
            if change.get("ai_explanation"):
                parts.append(f"<p>{esc(change['ai_explanation'])}</p>")
            if change.get("new_html"):
                parts.append(change["new_html"])
            elif change.get("old_html"):
                parts.append(change["old_html"])
    else:
        reply = client.reply_text(job)
        parts.append("<h2>Model reply</h2>")
        parts.append(f"<pre>{esc(reply)}</pre>")
    parts.append("</body></html>")
    return "\n".join(parts)


def draft_merges(mapping, run_id, output_dir):
    """HITL merge drafts: blank doc + chat_async(ask_every_time, pro). Do not approve here."""
    drafts_dir = Path(output_dir) / "merged_drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    merges = []
    for i, policy in enumerate(mapping.get("policies") or [], start=1):
        if policy.get("recommendation") != "merge":
            continue
        doc_a, doc_b = policy.get("doc_a"), policy.get("doc_b")
        paths = [d.get("path") for d in (doc_a, doc_b) if d and d.get("path")]
        if len(paths) < 2:
            print(f"  skip merge {policy['id']}: need two source files")
            continue
        merge_id = str(policy.get("id") or f"merge_{i:03d}")
        session_id = f"pr_{slug(run_id, 24)}_merge_{slug(merge_id, 20)}"
        print(f"  draft merge {merge_id} in session {session_id}")
        _open_docs_as_tabs(paths, session_id)
        blank = client.new_blank_document(session_id)
        target_id = blank.get("document_id")
        prompt = MERGE_PROMPT.format(
            title=policy.get("title") or "Merged policy",
            evidence=policy.get("evidence") or "",
            doc_a=(doc_a or {}).get("filename"),
            doc_b=(doc_b or {}).get("filename"),
        )
        job = client.chat_async(
            prompt,
            session_id,
            document_id=target_id,
            model_tier="pro",
            approval_mode="ask_every_time",
            allow_approval=True,
        )
        pending = client.parse_pending_changes((job.get("metadata") or {}).get("pending_changes"))
        draft_name = slug((doc_a or {}).get("stem") or merge_id) + ".html"
        draft_path = drafts_dir / draft_name
        draft_path.write_text(_draft_html(policy, pending, job), encoding="utf-8")
        merges.append(
            {
                "id": merge_id if merge_id.startswith("merge_") else f"merge_{merge_id}",
                "policy_id": policy["id"],
                "title": policy.get("title"),
                "session_id": session_id,
                "document_id": target_id,
                "job_id": job.get("job_id"),
                "status": job.get("status"),
                "pending_changes": pending,
                "proposed_draft_ref": f"merged_drafts/{draft_name}",
            }
        )
    return merges
