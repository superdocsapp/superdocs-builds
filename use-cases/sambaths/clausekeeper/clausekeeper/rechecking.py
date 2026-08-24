import yaml
from pathlib import Path

from . import db, guards, ingest, narrative


def detect_changed(client, conn) -> dict:
    session_id = db.get_meta(conn, "session_id")
    cursor = int(db.get_meta(conn, "doc_events_cursor", "0"))
    feed = client.doc_events(session_id, after_id=cursor)

    changed, renamed_set, skipped_echo, skipped_roles = {}, set(), 0, 0
    max_event = cursor
    for event in feed.get("events", []):
        event_id = int(event.get("event_id", max_event))
        max_event = max(max_event, event_id)
        slot = event.get("document_id")
        row = conn.execute(
            "SELECT * FROM documents WHERE session_slot_id = ?",
            (slot,)).fetchone()
        if not row:
            continue
        etype = event.get("type", "")
        if etype == "document_renamed":
            conn.execute("UPDATE documents SET name = ? WHERE"
                         " session_slot_id = ?",
                         (event.get("new_name") or row["name"], slot))
            renamed_set.add(slot)
            continue
        if guards.is_echo(event, conn):
            skipped_echo += 1
            continue
        if not guards.role_allows(dict(row)):
            skipped_roles += 1
            continue
        changed[slot] = dict(row)
    conn.commit()
    db.set_meta(conn, "doc_events_cursor", str(max_event))

    roster_by_slot = {}
    for entry in client.roster(session_id, include_html=True,
                               report_changed=True):
        roster_by_slot[entry.get("document_id")] = entry

    def row_for(slot):
        return conn.execute(
            "SELECT * FROM documents WHERE session_slot_id = ?",
            (slot,)).fetchone()

    for slot, entry in roster_by_slot.items():
        row = row_for(slot)
        if not row:
            continue
        new_name = entry.get("name")
        if not new_name and row["durable_document_id"]:
            try:
                detail = client.document_detail(row["durable_document_id"])
                new_name = detail.get("title")
            except Exception:
                new_name = None
        if new_name and new_name != row["name"] and slot not in renamed_set:
            conn.execute(
                "UPDATE documents SET name = ? WHERE session_slot_id = ?",
                (new_name, slot))
            renamed_set.add(slot)
        if entry.get("changed") and guards.role_allows(dict(row)):
            changed.setdefault(slot, dict(row))

    for row in conn.execute(
            "SELECT * FROM documents WHERE needs_verify = 1").fetchall():
        if guards.role_allows(dict(row)):
            changed.setdefault(row["session_slot_id"], dict(row))

    for slot, entry in roster_by_slot.items():
        row = row_for(slot)
        if not row or not guards.role_allows(dict(row)):
            continue
        html = entry.get("html") or ""
        new_hash = ingest.content_hash(html)
        if row["version_hash"] and new_hash != row["version_hash"] \
                and not guards.already_run(
                    conn, f"{slot}:{new_hash}"):
            changed.setdefault(slot, dict(row))
    conn.commit()

    checked_now, already_checked = [], []
    for slot, doc in changed.items():
        html = (roster_by_slot.get(slot) or {}).get("html", "")
        doc["html"] = html
        new_hash = ingest.content_hash(html)
        doc["version_hash"] = new_hash
        run_key = f"{slot}:{new_hash}"
        doc["run_key"] = run_key
        if guards.already_run(conn, run_key):
            already_checked.append(doc)
        else:
            checked_now.append(doc)
    return {"changed": checked_now, "already_checked": already_checked,
            "renamed": len(renamed_set), "skipped_echo": skipped_echo,
            "skipped_roles": skipped_roles}


def affected_clauses(conn, durable_id) -> list[dict]:
    rows = conn.execute(
        "SELECT DISTINCT l.clause_id, c.title, c.expectation FROM links l "
        "JOIN clauses c ON c.clause_id = l.clause_id "
        "WHERE l.durable_document_id = ?", (durable_id,)).fetchall()
    return [dict(r) for r in rows]


def build_plan(client, conn, detection: dict, scope_clauses=None) -> dict:
    items = []
    est_ops = 0
    for doc in detection["changed"]:
        clauses = affected_clauses(conn, doc["durable_document_id"])
        if scope_clauses:
            allowed = set(scope_clauses)
            clauses = [c for c in clauses if c["clause_id"] in allowed]
        if not clauses:
            continue
        est_ops += 1
        items.append({"name": doc["name"], "slot": doc["session_slot_id"],
                      "clauses": [c["clause_id"] for c in clauses],
                      "estimated_ops": 1})
    return {"items": items, "estimated_ops": est_ops,
            "skips": len(detection["already_checked"])}


VERIFY_PROMPT = (
    "You are our quality-assurance assistant; I am the QA manager. One of our "
    "internal procedure documents is open in this session; it was recently "
    "edited and I need to know which clauses still have supporting sections."
    "\n\n"
    "Quietly read EVERY section from start to finish - do not stop partway to "
    "ask whether to continue - then answer once.\n\n"
    "Rules:\n"
    "- Analysis only: do not create, modify, export, or summarize into any "
    "document; reply in chat.\n"
    "- For each clause listed at the end return one object with keys: "
    "clause_id, status (\"covered\" or \"gap\"), heading_path (the exact "
    "title of a section that provides evidence, or null).\n"
    "- Include every listed clause even if all are gaps.\n"
    "- End your reply with the complete array in a ```json fenced code block."
    "\n\nClauses: {clauses}"
)


def run_recheck(client, conn, scope_clauses=None) -> dict:
    detection = detect_changed(client, conn)
    session_id = db.get_meta(conn, "session_id")
    ops_before = sum(u["ops_charged"] for u in client.usage_log)
    turns = 0
    results = []
    for doc in detection["changed"]:
        if turns >= config_max_turns():
            results.append({"name": doc["name"], "status": "deferred",
                            "reason": "max-turns cap"})
            continue
        clauses = affected_clauses(conn, doc["durable_document_id"])
        if scope_clauses:
            allowed = set(scope_clauses)
            clauses = [c for c in clauses if c["clause_id"] in allowed]
        if not clauses:
            results.append({"name": doc["name"], "status": "skipped",
                            "reason": "no affected clauses in scope"})
            continue
        turns += 1
        clause_list = "; ".join(
            f"{c['clause_id']} ({c['title']}): {c['expectation']}"
            for c in clauses) or "(no linked clauses)"
        resp = client.chat_wait(
            VERIFY_PROMPT.replace("{clauses}", clause_list), session_id,
            document_id=doc["session_slot_id"],
            latency_class="verification_turn")
        try:
            verdicts = parse_verdicts(resp.get("response", ""))
        except ValueError as exc:
            print(f"WARN: could not parse verification verdicts for "
                  f"{doc['name']}: {exc}")
            results.append({"name": doc["name"], "status": "unparsed",
                            "reason": str(exc)[:120]})
            continue
        job_id = resp.get("job_id") or "sync-chat"
        now = db.now()
        chunks = ingest.extract_chunks(doc.get("html", ""))
        gaps_created = _apply_verdicts(conn, doc, verdicts, job_id, now,
                                       chunks)
        charged = _ops(resp)
        guards.mark_run(conn, doc["run_key"], "recheck", charged)
        conn.execute(
            "UPDATE documents SET version_hash = ?, needs_verify = 0"
            " WHERE session_slot_id = ?",
            (doc["version_hash"], doc["session_slot_id"]))
        results.append({"name": doc["name"], "clauses_checked": len(clauses),
                        "gaps": gaps_created, "ops_charged": charged})
    total_ops = sum(u["ops_charged"] for u in client.usage_log) - ops_before
    return {"results": results, "ops_spent": total_ops,
            "already_checked": [d["name"] for d in detection["already_checked"]],
            "echo_suppressed": detection["skipped_echo"],
            "roles_filtered": detection["skipped_roles"]}


def config_max_turns() -> int:
    from . import config
    return config.MAX_TURNS_PER_RUN


def parse_verdicts(text: str) -> list[dict]:
    from .superdocs import parse_json_block
    out = parse_json_block(text)
    return out if isinstance(out, list) else []


def _ops(resp: dict) -> int:
    return int((resp.get("usage") or {}).get("ops_charged", 0))


def linking_split(heading):
    from .linking import _split_headings
    return _split_headings(heading)


def _apply_verdicts(conn, doc, verdicts, job_id, now, chunks=None) -> int:
    chunks = chunks or []
    by_chunk = {c["chunk_id"]: c for c in chunks}
    gaps_created = 0
    kept_chunks: dict[str, set] = {}
    for v in verdicts:
        cid = str(v.get("clause_id"))
        status = str(v.get("status", "")).lower()
        if status == "covered":
            headings = linking_split(v.get("heading_path"))
            if not headings:
                print(f"WARN: {doc['name']}: clause {cid} marked covered "
                      f"without a section; skipped")
                continue
            kept = kept_chunks.setdefault(cid, set())
            for heading in headings:
                chunk = None
                if v.get("chunk_id"):
                    chunk = by_chunk.get(str(v["chunk_id"]))
                if not chunk:
                    chunk = ingest.find_chunk_by_heading(chunks, heading)
                if not chunk:
                    print(f"WARN: {doc['name']}: could not resolve section "
                          f"'{heading}' for clause {cid}; skipped")
                    continue
                kept.add(chunk["chunk_id"])
                chunk_id = chunk["chunk_id"]
                final_heading = heading or chunk["heading_path"]
                quote = chunk["quote_excerpt"]
                conn.execute(
                    "INSERT INTO links(clause_id, durable_document_id,"
                    " chunk_id, heading_path, quote_excerpt, status,"
                    " last_verified_at, last_verified_job)"
                    " VALUES(?,?,?,?,?,'covered',?,?)"
                    " ON CONFLICT(clause_id, durable_document_id, chunk_id)"
                    " DO UPDATE SET status='covered', heading_path=excluded."
                    " heading_path, quote_excerpt=excluded.quote_excerpt,"
                    " last_verified_at=excluded.last_verified_at,"
                    " last_verified_job=excluded.last_verified_job",
                    (cid, doc["durable_document_id"], chunk_id,
                     final_heading, quote[:200], now, job_id))
        elif status == "gap":
            updated = conn.execute(
                "UPDATE links SET status='gap', last_verified_at=?,"
                " last_verified_job=? WHERE clause_id=? AND"
                " durable_document_id=? AND status != 'gap'",
                (now, job_id, cid, doc["durable_document_id"]))
            if updated.rowcount > 0 and not conn.execute(
                    "SELECT 1 FROM gaps WHERE clause_id = ? AND"
                    " durable_document_id = ?",
                    (cid, doc["durable_document_id"])).fetchone():
                cause = conn.execute(
                    "SELECT edit_id FROM edits WHERE durable_document_id = ?"
                    " ORDER BY edit_id DESC LIMIT 1",
                    (doc["durable_document_id"],)).fetchone()
                text = narrative.verification_gap_narrative(cid, job_id, now)
                conn.execute(
                    "INSERT INTO gaps(clause_id, durable_document_id,"
                    " cause_edit_id, detected_at, narrative) VALUES(?,?,?,?,?)",
                    (cid, doc["durable_document_id"],
                     cause["edit_id"] if cause else 0, now, text))
                gaps_created += 1
    for cid, kept in kept_chunks.items():
        if kept:
            placeholders = ",".join("?" * len(kept))
            conn.execute(
                "DELETE FROM links WHERE clause_id = ? AND"
                " durable_document_id = ? AND chunk_id NOT IN (%s)" %
                placeholders,
                (cid, doc["durable_document_id"], *kept))
        conn.execute(
            "DELETE FROM gaps WHERE clause_id = ? AND durable_document_id = ?",
            (cid, doc["durable_document_id"]))
    conn.commit()
    return gaps_created


def load_scope(expected_path=None):
    if expected_path and Path(expected_path).exists():
        raw = yaml.safe_load(Path(expected_path).read_text())
        seeds = [str(s["clause_id"]) for s in raw.get("seeds", [])]
        scripted = raw.get("scripted_edit", {})
        if scripted.get("expected_gap_clause"):
            seeds.append(str(scripted["expected_gap_clause"]))
        return seeds
    return None
