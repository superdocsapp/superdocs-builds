import os

from . import db, ingest, narrative
from .superdocs import OpsFloorExceeded


def default_decider(change: dict):
    print(f"\nProposed {change.get('operation')} on chunk "
          f"{change.get('chunk_id')}")
    old = (change.get("old_html") or "")[:200]
    new = (change.get("new_html") or "")[:200]
    print(f"  old: {old}\n  new: {new}")
    try:
        answer = input("Approve? [y/N]: ").strip().lower()
    except (EOFError, OSError):
        if os.environ.get("CK_AUTO_APPROVE") == "1":
            print("  [CK_AUTO_APPROVE=1 - approving without a terminal]")
            return True
        raise SystemExit(
            "no interactive terminal to decide this change; run in a TTY "
            "or set CK_AUTO_APPROVE=1 to approve scripted demo edits")
    return answer == "y"


def guided_edit(client, conn, doc_query: str, instruction: str,
                decide=None, latency_class: str = "complex_edit") -> dict:
    decide = decide or default_decider
    session_id = db.get_meta(conn, "session_id")
    doc = _resolve_doc(conn, doc_query)

    start = client.chat_async(
        instruction, session_id, document_id=doc["session_slot_id"],
        approval_mode="ask_every_time")
    job_id = start["job_id"]
    client.register_our_job(conn, job_id, f"guided-edit:{doc['name']}")

    while True:
        job = client.poll_job(job_id, latency_class,
                              pause_on={"awaiting_approval"})
        status = job.get("status")
        if status in ("failed", "cancelled"):
            raise RuntimeError(f"edit job {job_id} ended {status}: "
                               f"{str(job.get('error'))[:300]}")
        if status == "awaiting_approval":
            meta = job.get("metadata") or {}
            if meta.get("awaiting_kind") == "continue_prompt":
                client.continue_chat(session_id, job_id, True)
                continue
            decisions = []
            for change in meta.get("pending_changes", []):
                outcome = decide(change)
                approved, feedback = outcome if isinstance(outcome, tuple) \
                    else (outcome, None)
                entry = {"change_id": change["change_id"],
                         "approved": bool(approved)}
                if feedback:
                    entry["feedback"] = feedback
                decisions.append(entry)
            if decisions:
                client.approve(session_id, job_id, decisions,
                               default_approved=all(
                                   d["approved"] for d in decisions))
            continue

        result = job.get("result") or {}
        client.capture_job_result(job)
        summary = _process_completed(client, conn, doc, job_id, instruction,
                                     result, job)
        summary["status"] = status
        return summary


def _resolve_doc(conn, query: str):
    row = conn.execute(
        "SELECT * FROM documents WHERE name LIKE ? OR session_slot_id = ?",
        (f"%{query}%", query)).fetchone()
    if not row:
        raise SystemExit(f"no document matches '{query}' in this session")
    return row


def _process_completed(client, conn, doc, job_id, instruction, result,
                       job) -> dict:
    occurred_at = _job_time(job)
    diffs = ((result.get("document_changes") or {}).get("chunk_diffs")) or []
    now = db.now()
    gap_count = 0
    for diff in diffs:
        cur = conn.execute(
            "INSERT INTO edits(job_id, change_id, durable_document_id, "
            "session_slot_id, chunk_id, operation, old_excerpt, new_excerpt,"
            " occurred_at, causing_instruction, origin) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, diff.get("change_id"), doc["durable_document_id"],
             doc["session_slot_id"], diff.get("chunk_id"),
             diff.get("operation"),
             _excerpt(diff.get("old_html")), _excerpt(diff.get("new_html")),
             occurred_at, instruction, "api"))
        edit_id = cur.lastrowid
        if diff.get("operation") in ("delete", "edit"):
            gap_count += _land_gaps(conn, doc, diff, edit_id, instruction,
                                    job_id, occurred_at, now)
    _refresh_version_hash(client, conn, doc)
    conn.execute(
        "UPDATE documents SET needs_verify = 1 WHERE session_slot_id = ?",
        (doc["session_slot_id"],))
    conn.commit()
    return {"job_id": job_id, "edits_recorded": len(diffs),
            "gaps_landed": gap_count}


def _land_gaps(conn, doc, diff, edit_id, instruction, job_id, occurred_at,
               now) -> int:
    def links_for(chunk_ids):
        if not chunk_ids:
            return []
        placeholders = ",".join("?" * len(chunk_ids))
        return conn.execute(
            "SELECT l.link_id, l.clause_id FROM links l WHERE "
            "l.durable_document_id = ? AND l.chunk_id IN (%s) "
            "AND l.status != 'gap'" % placeholders,
            (doc["durable_document_id"], *chunk_ids)).fetchall()

    rows = links_for({diff.get("chunk_id")})
    if not rows:
        swept = set(ingest.CHUNK_RE.findall(diff.get("old_html") or ""))
        swept.discard(None)
        rows = links_for(swept)
    count = 0
    seen_clauses = set()
    for row in rows:
        clause = conn.execute("SELECT title FROM clauses WHERE clause_id = ?",
                              (row["clause_id"],)).fetchone()
        text = narrative.gap_narrative(
            row["clause_id"], _heading_of(diff), diff.get("operation"),
            diff.get("change_id"), instruction, job_id, occurred_at)
        conn.execute("UPDATE links SET status = 'gap', last_verified_at = ?,"
                     " last_verified_job = ? WHERE link_id = ?",
                     (now, job_id, row["link_id"]))
        if row["clause_id"] not in seen_clauses:
            conn.execute(
                "INSERT INTO gaps(clause_id, durable_document_id,"
                " cause_edit_id, detected_at, narrative) VALUES(?,?,?,?,?)",
                (row["clause_id"], doc["durable_document_id"], edit_id, now,
                 text))
            seen_clauses.add(row["clause_id"])
            count += 1
        print(f"GAP LANDED: clause {row['clause_id']} ({title_of(clause)})"
              f"\n  {text}")
    return count


def title_of(clause) -> str:
    return clause["title"] if clause else ""


def _heading_of(diff) -> str:
    new_html = diff.get("new_html") or ""
    match = ingest.HEADING_RE.search(new_html)
    if match:
        return ingest.TAG_RE.sub("", match.group(2)).strip()
    old_html = diff.get("old_html") or ""
    match = ingest.HEADING_RE.search(old_html)
    return ingest.TAG_RE.sub("", match.group(2)).strip() if match \
        else "(section)"


def _excerpt(html) -> str:
    import re as _re
    text = _re.sub(r"<[^>]+>", " ", html or "")
    return _re.sub(r"\s+", " ", text).strip()[:200]


def _refresh_version_hash(client, conn, doc):
    session_id = db.get_meta(conn, "session_id")
    try:
        roster = client.roster(session_id, include_html=True)
        entry = next((d for d in roster
                      if d["document_id"] == doc["session_slot_id"]), {})
        html = entry.get("html", "")
        conn.execute(
            "UPDATE documents SET version_hash = ?, name = COALESCE(?, name)"
            " WHERE session_slot_id = ?",
            (ingest.content_hash(html), entry.get("name"),
             doc["session_slot_id"]))
    except Exception:
        pass


def _job_time(job) -> str:
    for key in ("completed_at", "updated_at", "finished_at"):
        stamp = job.get(key)
        if stamp:
            return stamp
    result = job.get("result") or {}
    for key in ("completed_at", "updated_at"):
        if result.get(key):
            return result[key]
    return db.now()
