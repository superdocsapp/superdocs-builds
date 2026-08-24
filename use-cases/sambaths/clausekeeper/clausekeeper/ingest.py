import hashlib
import re
from pathlib import Path

from . import db


def role_for(filename: str) -> str:
    return "manual" if "manual" in filename.lower() else "procedure"


def init_session(client, conn, corpus_dir: str) -> dict:
    session = client.create_session()
    session_id = session["session_id"]
    db.set_meta(conn, "session_id", session_id)
    conn.execute("DELETE FROM gaps")
    conn.execute("DELETE FROM links")
    conn.execute("DELETE FROM edits")
    conn.execute("DELETE FROM runs")
    conn.execute("DELETE FROM our_jobs")
    conn.execute("DELETE FROM shortlists")
    conn.execute("DELETE FROM documents")

    corpus = Path(corpus_dir)
    for path in sorted(corpus.glob("*.md")):
        upload = client.upload_document(session_id, str(path),
                                        open_mode="new_focused")
        slot_id = upload.get("document_id") or upload.get("doc_id")
        if not slot_id:
            raise RuntimeError(f"upload response missing document id: "
                               f"{list(upload)}")
        client.save_document(session_id, slot_id,
                             upload.get("html", ""), upload.get("html", ""))
        conn.execute(
            "INSERT OR REPLACE INTO documents(session_slot_id, role, name, "
            "version_hash, bound_at) VALUES(?, ?, ?, ?, ?)",
            (slot_id, role_for(path.name), path.stem, "", db.now()))

    bind_durable_ids(client, conn)
    roster = {d["document_id"]: d for d in
              client.roster(session_id, include_html=True)}
    for row in conn.execute("SELECT session_slot_id FROM documents").fetchall():
        entry = roster.get(row["session_slot_id"], {})
        html = entry.get("html", "")
        conn.execute(
            "UPDATE documents SET version_hash = ? WHERE session_slot_id = ?",
            (content_hash(html), row["session_slot_id"]))
    conn.commit()
    count = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
    unbound = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE durable_document_id IS NULL"
    ).fetchone()["c"]
    return {"session_id": session_id, "documents": count, "unbound": unbound}


def bind_durable_ids(client, conn):
    session_id = db.get_meta(conn, "session_id")
    for entry in client.roster(session_id):
        durable = entry.get("durable_document_id")
        if not durable:
            continue
        conn.execute(
            "UPDATE documents SET durable_document_id = ?, name = COALESCE(?, name)"
            ", bound_at = COALESCE(bound_at, ?) WHERE session_slot_id = ?",
            (durable, entry.get("name"), db.now(), entry["document_id"]))
    conn.commit()


def content_hash(html: str) -> str:
    return hashlib.sha256((html or "").encode()).hexdigest()


CHUNK_RE = re.compile(r'data-chunk-id="([^"]+)"')
HEADING_RE = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def _norm(text: str) -> str:
    text = TAG_RE.sub("", text or "").lower()
    text = re.sub(r"^\s*\d+(\.\d+)*\s*", "", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def best_chunk_match(chunks: list[dict], heading) -> tuple[dict | None, float]:
    if not heading:
        return None, 0.0
    target = _norm(str(heading))
    if not target:
        return None, 0.0
    best, best_score = None, 0.0
    for c in chunks:
        cand = _norm(c["heading_path"])
        full = _norm(c["heading_path"].split(">")[-1])
        if not cand:
            continue
        if target == cand or target == full:
            return c, 1.0
        score = 0.0
        if target in cand or cand in target:
            score = max(len(target), len(cand)) / (
                min(len(target), len(cand)) + 1e-9)
            score = min(score, 1.0)
        else:
            t_tokens, c_tokens = set(target.split()), set(cand.split())
            if t_tokens and c_tokens:
                score = len(t_tokens & c_tokens) / len(
                    t_tokens | c_tokens)
        if score > best_score:
            best, best_score = c, score
    return (best if best_score >= 0.5 else None), best_score


def find_chunk_by_heading(chunks: list[dict], heading) -> dict | None:
    return best_chunk_match(chunks, heading)[0]


def extract_chunks(html: str) -> list[dict]:
    positions = []
    for m in CHUNK_RE.finditer(html):
        tag_end = html.find(">", m.start())
        if tag_end == -1:
            continue
        positions.append((tag_end + 1, m.group(1)))
    if not positions:
        return []
    headings = [(m.start(), int(m.group(1)),
                 TAG_RE.sub("", m.group(2)).strip())
                for m in HEADING_RE.finditer(html)]
    out = []
    seen = 0
    stack: dict[int, str] = {}
    for idx, (start, cid) in enumerate(positions):
        end = positions[idx + 1][0] if idx + 1 < len(positions) else len(html)
        while seen < len(headings) and headings[seen][0] < end:
            _, level, text = headings[seen]
            for k in [k for k in list(stack) if k >= level]:
                del stack[k]
            stack[level] = text
            seen += 1
        parts = [stack[k] for k in sorted(stack)]
        body = html[start:end]
        quote = re.sub(r"\s+", " ", TAG_RE.sub(" ", body)).strip()
        out.append({
            "chunk_id": cid,
            "heading_path": " > ".join(parts) if parts else "(front matter)",
            "quote_excerpt": quote[:200],
        })
    return out
