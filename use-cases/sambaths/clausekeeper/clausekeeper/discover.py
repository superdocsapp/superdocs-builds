import json as _json

from . import db, ingest
from .superdocs import parse_json_block

SEARCH_PROMPT = (
    "Search across ALL open documents in this session. For EACH ISO 9001 "
    "clause listed below, shortlist candidate evidence sections.\n\n"
    "Reply with ONLY a JSON array of objects with keys: clause_id, "
    "durable_document_id, heading (the exact section title in the document), "
    "chunk_id_if_known (or null), why (one short phrase).\n"
    "- Only name sections that actually exist in the open documents.\n"
    "- Cover every listed clause; when a clause has no supporting section "
    "anywhere, return no entry for it rather than inventing one.\n\n"
    "Clauses: {clauses}"
)


def bound_documents(conn):
    return conn.execute(
        "SELECT * FROM documents WHERE role != 'generated' "
        "AND durable_document_id IS NOT NULL").fetchall()


def run_discover(client, conn, clauses) -> dict:
    print("DISCOVER pass (opt-in): shortlisting evidence sections before"
          " mapping")
    docs, linkable, rows = _local_shortlist(client, conn, clauses, echo=True)
    resolved = {r["clause_id"] for r in rows}
    unresolved = [c for c in linkable if c["id"] not in resolved]
    print(f"  local match resolved {len(linkable) - len(unresolved)}/"
          f"{len(linkable)} linkable clauses from headings alone (0 ops)")
    ops = 0
    if unresolved:
        print(f"  unresolved: {', '.join(c['id'] for c in unresolved)} ->"
              f" one batched search turn across all open documents")
        if docs:
            names = {d["durable_document_id"]: d["name"] for d in docs}
            search_rows, ops = _search_fallback(
                client, conn, unresolved, len(docs), names)
            rows.extend(search_rows)
        else:
            print("  WARN: no bound documents to search - continuing with"
                  " standard mapping")
    else:
        print("  search turn skipped - local shortlist covered every clause"
              " (0 ops)")
    _persist_shortlists(conn, rows)
    _print_shortlist(rows, linkable)
    return {"rows": rows, "ops_charged": ops}


def plan_discover(client, conn, clauses) -> int:
    docs, linkable, rows = _local_shortlist(client, conn, clauses)
    resolved = {r["clause_id"] for r in rows}
    unresolved = [c for c in linkable if c["id"] not in resolved]
    projected = 1 if (unresolved and docs) else 0
    print("DISCOVER PLAN (preview mode - zero billable ops)")
    print(f"  would free-read {len(docs)} bound documents (0 ops)")
    print(f"  local match projects {len(linkable) - len(unresolved)}/"
          f"{len(linkable)} resolvable from headings (0 ops)")
    if projected:
        print(f"  projected search spend: {projected} op (one batched turn"
              f" for {', '.join(c['id'] for c in unresolved)})")
    else:
        print("  projected search spend: 0 op (none needed)")
    print(f"  estimated cost: <={projected} op{'s' if projected != 1 else ''};"
          f" spent so far: 0")
    return projected


def _local_shortlist(client, conn, clauses, echo=False):
    session_id = db.get_meta(conn, "session_id")
    docs = bound_documents(conn)
    roster = {d["document_id"]: d for d in
              client.roster(session_id, include_html=True)}
    linkable = [c for c in clauses if c["linkable"]]
    rows = []
    for doc in docs:
        entry = roster.get(doc["session_slot_id"], {})
        html = entry.get("html") or ""
        chunks = ingest.extract_chunks(html)
        if echo:
            print(f"  free read  {_leader(doc['name'])} {len(chunks)}"
                  f" sections")
        for clause in linkable:
            chunk, score = ingest.best_chunk_match(chunks, clause["title"])
            source_score = score
            if chunk is None:
                hit = _number_prefix_hit(chunks, clause["id"])
                if hit is not None:
                    chunk, source_score = hit, 1.0
            if chunk is not None:
                rows.append({
                    "clause_id": clause["id"],
                    "doc_name": doc["name"],
                    "durable_document_id": doc["durable_document_id"],
                    "chunk_id": chunk["chunk_id"],
                    "heading_path": chunk["heading_path"],
                    "source": "local",
                    "score": float(source_score),
                })
    return docs, linkable, rows


def _search_fallback(client, conn, unresolved, doc_count, names_by_durable):
    clause_list = "; ".join(
        f"{c['id']} ({c['title']})" for c in unresolved)
    message = (SEARCH_PROMPT
               .replace("{clauses}", clause_list)
               .replace("{doc_count}", str(doc_count)))
    session_id = db.get_meta(conn, "session_id")
    resp = client.chat_wait(message, session_id,
                            latency_class="verification_turn")
    usage = resp.get("usage") or {}
    charged = usage.get("ops_charged")
    if "usage" not in resp or charged is None or int(charged) > 1:
        raise RuntimeError(
            f"discover search turn reported usage ops_charged={charged};"
            f" contract caps the batched pass at 1 op - refusing to"
            f" continue")
    ops = int(charged)
    print(f"  [search] charged {ops} op{'s' if ops != 1 else ''}"
          f" (was_billable="
          f"{str(bool(usage.get('was_billable'))).lower()},"
          f" ops_charged={ops})")
    allowed = {c["id"] for c in unresolved}
    rows = _parse_search_rows(resp.get("response", ""), allowed,
                              names_by_durable)
    covered = len({r["clause_id"] for r in rows})
    if covered < len(unresolved):
        print(f"  WARN: search returned usable candidates for only"
              f" {covered} of {len(unresolved)} unresolved clauses")
        print(f"  WARN: discover could not shortlist "
              f"{len(unresolved) - covered} clauses - continuing with"
              f" standard mapping (no candidates invented)")
    else:
        print(f"  search resolved {covered}/{len(unresolved)} remaining"
              f" clauses")
    return rows, ops


def _parse_search_rows(text, allowed_ids, names_by_durable):
    items = _loads_lenient(text)
    if not isinstance(items, list):
        return []
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("clause_id", "")).strip()
        if cid not in allowed_ids:
            continue
        heading = str(item.get("heading") or "").strip()
        if not heading:
            continue
        durable = str(item.get("durable_document_id") or "").strip() or None
        chunk = str(item.get("chunk_id_if_known") or "").strip() or None
        rows.append({
            "clause_id": cid,
            "doc_name": names_by_durable.get(durable, durable),
            "durable_document_id": durable,
            "chunk_id": chunk,
            "heading_path": heading,
            "source": "search",
            "score": None,
        })
    return rows


def _loads_lenient(text):
    current = text
    for _ in range(3):
        if not isinstance(current, str):
            break
        stripped = current.strip()
        if stripped.startswith('"') and stripped.endswith('"'):
            try:
                current = _json.loads(stripped)
                continue
            except _json.JSONDecodeError:
                break
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                current = _json.loads(stripped)
                continue
            except _json.JSONDecodeError:
                break
        break
    if isinstance(current, list):
        return current
    try:
        return parse_json_block(text if isinstance(text, str) else "")
    except (ValueError, _json.JSONDecodeError):
        return []


def _number_prefix_hit(chunks, clause_id):
    cid = str(clause_id).strip()
    for c in chunks:
        for segment in str(c["heading_path"]).split(">"):
            seg = segment.strip().lower()
            if seg == cid or seg.startswith(cid + " "):
                return c
    return None


def _persist_shortlists(conn, rows):
    now = db.now()
    for r in rows:
        conn.execute(
            "INSERT INTO shortlists(clause_id, durable_document_id,"
            " chunk_id, heading_path, source, score, discovered_at)"
            " VALUES(?, ?, ?, ?, ?, ?, ?)",
            (r["clause_id"], r["durable_document_id"], r["chunk_id"],
             r["heading_path"], r["source"], r["score"], now))
    conn.commit()


def _print_shortlist(rows, linkable):
    if not rows:
        return
    order = {c["id"]: i for i, c in enumerate(linkable)}
    ordered = sorted(rows, key=lambda r: (
        order.get(r["clause_id"], len(order)),
        r["durable_document_id"] or ""))
    print("SHORTLIST (candidates found before mapping)")
    print(f"{'CLAUSE':<8}{'DOCUMENT':<27}{'CANDIDATE SECTION':<41}SOURCE")
    for r in ordered:
        doc = (r["doc_name"] or "")[:26]
        heading = r["heading_path"][:40]
        print(f"{r['clause_id']:<8}{doc:<27}{heading:<41}{r['source']}")


def _leader(name: str) -> str:
    return f"{name} {'.' * max(3, 38 - len(name))}"
