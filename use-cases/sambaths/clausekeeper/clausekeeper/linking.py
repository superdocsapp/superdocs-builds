import json as _json
import re

import yaml

from . import db, ingest
from .superdocs import parse_json_block

LINK_PROMPT = (
    "You are our quality-assurance assistant working inside our organization's "
    "documentation workspace; I am the QA manager. One of our internal "
    "procedure documents is open in this session.\n\n"
    "Task: quietly read EVERY section of the document from start to finish - "
    "do not stop partway and ask whether to continue - then produce a clause "
    "coverage index for the ISO 9001:2015 clauses listed at the end.\n\n"
    "Rules:\n"
    "- Analysis only: do not create, modify, export, or summarize into any "
    "document; reply in chat.\n"
    "- Answer once, after reading everything.\n"
    "- For each listed clause return one object with keys: clause_id, status "
    "(\"covered\" or \"not-covered\"), heading_path (the exact title of the "
    "section in our document that provides evidence, or null).\n"
    "- Pick the single MOST specific evidencing section - a section about "
    "control of defective product evidences the nonconforming-output clause, "
    "not the documented-information clause.\n"
    "- Passing mentions never count: \"covered\" requires a dedicated section "
    "that a reader could follow to see how our organization does this. When "
    "the document only alludes to a topic, answer not-covered.\n"
    "- Include every listed clause even if none are covered.\n"
    "- End your reply with the complete array in a ```json fenced code block."
    "\n\nClauses: {clauses}"
)


def build_links(client, conn, clauses: list[dict]):
    session_id = db.get_meta(conn, "session_id")
    results = []
    docs = conn.execute(
        "SELECT * FROM documents WHERE role != 'generated' "
        "AND durable_document_id IS NOT NULL").fetchall()
    roster = {d["document_id"]: d for d in
              client.roster(session_id, include_html=True)}
    for doc in docs:
        entry = roster.get(doc["session_slot_id"], {})
        html = entry.get("html") or ""
        if not html.strip():
            results.append({"doc": doc["name"], "links_added": 0,
                            "ops_charged": 0, "parse_failed": False,
                            "skipped": "no html in roster"})
            continue
        chunks = ingest.extract_chunks(html)
        clause_list = "; ".join(
            f"{c['id']} ({c['title']})" for c in clauses if c["linkable"])
        resp = client.chat_wait(
            LINK_PROMPT.replace("{clauses}", clause_list), session_id,
            document_id=doc["session_slot_id"],
            latency_class="verification_turn")
        try:
            mappings = parse_json_block(resp.get("response", ""))
            if not isinstance(mappings, list):
                raise ValueError("mapping is not a JSON array")
        except (ValueError, _json.JSONDecodeError) as exc:
            print(f"WARN: could not parse mapping for {doc['name']}: {exc}")
            results.append({"doc": doc["name"], "links_added": 0,
                            "ops_charged": _ops(resp), "parse_failed": True})
            continue
        by_chunk = {c["chunk_id"]: c for c in chunks}
        job_id = resp.get("job_id") or "sync-chat"
        now = db.now()
        added = 0
        for m in mappings:
            if str(m.get("status", "")).lower() != "covered":
                continue
            headings = _split_headings(m.get("heading_path"))
            if not headings:
                print(f"WARN: {doc['name']}: clause {m.get('clause_id')} "
                      f"marked covered without a section; skipped")
                continue
            for heading in headings:
                chunk = None
                if m.get("chunk_id"):
                    chunk = by_chunk.get(str(m.get("chunk_id")))
                if not chunk:
                    chunk = ingest.find_chunk_by_heading(chunks, heading)
                if not chunk:
                    print(f"WARN: {doc['name']}: could not resolve section "
                          f"'{heading}' for clause {m.get('clause_id')}; "
                          f"skipped")
                    continue
                final_heading = heading or chunk["heading_path"]
                quote = chunk["quote_excerpt"]
                conn.execute(
                    "INSERT OR IGNORE INTO links(clause_id,"
                    " durable_document_id, chunk_id, heading_path,"
                    " quote_excerpt, status, last_verified_at,"
                    " last_verified_job) VALUES(?, ?, ?, ?, ?, 'covered',"
                    " ?, ?)",
                    (str(m["clause_id"]), doc["durable_document_id"],
                     chunk["chunk_id"], final_heading, quote[:200], now,
                     job_id))
                added += 1
        conn.commit()
        results.append({"doc": doc["name"], "links_added": added,
                        "ops_charged": _ops(resp), "parse_failed": False})
    return results


def _split_headings(heading) -> list[str]:
    if not heading or not str(heading).strip():
        return []
    parts = re.split(r"[;]| \+ |, and ", str(heading))
    return [p.strip(" .;-") for p in parts if p.strip(" .;-")][:6]


def _ops(resp: dict) -> int:
    return int((resp.get("usage") or {}).get("ops_charged", 0))


def audit_against_expected(conn, expected_path):
    linked = {r["clause_id"] for r in conn.execute(
        "SELECT DISTINCT clause_id FROM links WHERE status != 'gap'")}
    uncovered = []
    raw = yaml.safe_load(__import__("pathlib").Path(expected_path).read_text())
    for seed in raw.get("seeds", []):
        cid = str(seed["clause_id"])
        uncovered.append({"seed": seed["id"], "clause_id": cid,
                          "detected": cid not in linked})
    return uncovered
