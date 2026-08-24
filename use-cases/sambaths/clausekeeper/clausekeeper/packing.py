"""Audit-readiness pack: one generated document + branded export.

Builds the traceability matrix and summary into a single new in-session
document on the uploaded letterhead template, then exports it through the
pre-signed download lane, checking X-Export-Warnings every time.
"""

import re
from pathlib import Path

from . import db, guards
from .library import load_library
from .superdocs import SuperDocsClient

READINESS_PHRASE = ("readiness assessment against the ISO 9001:2015 "
                    "clause structure")
FORBIDDEN_RE = re.compile(r"certif", re.I)
DEFAULT_TITLE = "Northgate Medical Devices - Audit Readiness Pack"

HONEST_LIMITS = (
    "This pack is a readiness assessment against the ISO 9001:2015 clause "
    "structure only. It is not an audit, it grants no formal standing, and "
    "no external body has reviewed it. The clause list uses official "
    "identifiers and titles plus Northgate's own expectations; verification "
    "quality depends on the model tier behind the session, and gaps can be "
    "false positives until a human reviews them."
)

PROMPT_TEMPLATE = """You are our quality-assurance assistant; I am the QA manager at \
Northgate Medical Devices.

Create a NEW document titled "{title}" in this session, applying the \
branding of our uploaded letterhead template ({template_name}) - its page \
header, footer, fonts and colors should carry over. Do not modify any \
existing document.

This is one audit-readiness pack with two parts.

Part 1 - Traceability Matrix. One table row per line below, exactly as \
given: do not add, drop, merge or reinterpret rows. Columns: Clause | \
Clause title | Status | Evidence document | Section | Last verified.

{matrix_rows}

Clauses with no evidence anywhere: {uncovered_list}
Open gaps to repeat verbatim as bullets under the matrix:
{gap_bullets}

Part 2 - Summary page with exactly these figures and texts:
- Scope: {readiness_phrase} ({total} linkable clauses).
- Coverage: {covered} of {total} clauses have evidenced sections ({pct}%).
- Open gaps: {gap_count}. Uncovered clauses: {uncovered_count}.
- Stale checks: {stale} link(s) carry status "stale"; last-verified dates \
for every link appear in the matrix above.
- Honest limits paragraph, repeated verbatim:
"{honest_limits}"

Rules:
- Use the figures and wording provided here verbatim; do not compute your \
own statistics or invent rows.
- Frame everything as a {readiness_phrase}; never as conformity granted by \
any external body.
- Produce the document in one turn and reply briefly confirming its title.
"""


class LanguageRailError(RuntimeError):
    pass


def assert_language_rail(text: str) -> None:
    match = FORBIDDEN_RE.search(text or "")
    if match:
        start = max(0, match.start() - 60)
        raise LanguageRailError(
            f"forbidden claim token {match.group(0)!r} near: "
            f"…{text[start:match.end() + 60]}…")


def collect_matrix(conn, library_path: str | None = None) -> dict:
    rows = conn.execute(
        "SELECT l.clause_id, c.title AS clause_title, l.status, d.name AS"
        " doc, l.heading_path, l.last_verified_at FROM links l JOIN"
        " clauses c ON c.clause_id = l.clause_id JOIN documents d ON"
        " d.durable_document_id = l.durable_document_id ORDER BY"
        " l.clause_id, d.name").fetchall()
    library = load_library(library_path) if library_path else None
    linkable = [c for c in (library or []) if c.get("linkable")]
    linked_ids = {r["clause_id"] for r in rows}
    covered_ids = {r["clause_id"] for r in rows if r["status"] == "covered"}
    uncovered = [c for c in linkable if c["id"] not in linked_ids]
    if not linkable:
        total = len({r["clause_id"] for r in rows})
    else:
        total = len(linkable)
    covered = len(covered_ids)
    pct = round(100 * covered / total) if total else 0
    gaps = conn.execute(
        "SELECT g.clause_id, g.narrative, e.operation AS cause_op,"
        " e.change_id AS cause_change_id, e.causing_instruction AS"
        " cause_instruction, e.occurred_at AS cause_at FROM gaps g LEFT"
        " JOIN edits e ON e.edit_id = g.cause_edit_id WHERE g.gap_id IN"
        " (SELECT MAX(gap_id) FROM gaps GROUP BY clause_id,"
        " durable_document_id) ORDER BY g.clause_id").fetchall()
    stale = conn.execute(
        "SELECT COUNT(*) c FROM links WHERE status = 'stale'").fetchone()["c"]
    return {
        "rows": [dict(r) for r in rows],
        "covered": covered,
        "total": total,
        "pct": pct,
        "uncovered": [{"id": c["id"], "title": c["title"]}
                      for c in uncovered],
        "gaps": [dict(g) for g in gaps],
        "stale": stale,
    }


def matrix_rows_text(matrix: dict) -> str:
    lines = []
    for r in matrix["rows"]:
        verified = r["last_verified_at"] or "(pending)"
        section = (r["heading_path"] or "").replace("|", "/")[:80]
        lines.append(f"{r['clause_id']} | {r['clause_title']} | "
                     f"{r['status']} | {r['doc']} | {section} | {verified}")
    return "\n".join(lines) or "(no linked rows yet)"


def gap_bullets_text(matrix: dict) -> str:
    bullets = []
    for g in matrix["gaps"]:
        line = f"- {g['narrative']}"
        if g.get("cause_instruction"):
            line += (f" Causing edit: {g['cause_op']} by edit"
                     f" `{g['cause_change_id']}` at {g['cause_at']},"
                     f" instruction '{g['cause_instruction']}'.")
        bullets.append(line)
    return "\n".join(bullets) or "- (none)"


def render_prompt(matrix: dict, template_name: str,
                  title: str = DEFAULT_TITLE) -> str:
    uncovered_list = ", ".join(f"{c['id']} {c['title']}"
                               for c in matrix["uncovered"]) or "(none)"
    prompt = PROMPT_TEMPLATE.format(
        title=title, template_name=template_name,
        matrix_rows=matrix_rows_text(matrix),
        uncovered_list=uncovered_list, gap_bullets=gap_bullets_text(matrix),
        readiness_phrase=READINESS_PHRASE, honest_limits=HONEST_LIMITS,
        total=matrix["total"], covered=matrix["covered"],
        pct=matrix["pct"], gap_count=len(matrix["gaps"]),
        uncovered_count=len(matrix["uncovered"]), stale=matrix["stale"])
    assert_language_rail(prompt)
    return prompt


def ensure_template(client: SuperDocsClient, conn,
                    template_path: str | None) -> dict | None:
    stored = db.get_meta(conn, "pack_template_id")
    if stored:
        return {"template_id": stored, "reused": True}
    if not template_path:
        raise RuntimeError("branded pack needs --template PATH once; a "
                           "template id is already bound afterwards")
    info = client.upload_template(template_path)
    template_id = str(info.get("template_id") or info.get("id") or "")
    if not template_id:
        raise RuntimeError(f"template upload returned no id: {list(info)}")
    db.set_meta(conn, "pack_template_id", template_id)
    db.set_meta(conn, "pack_template_name", Path(template_path).name)
    return {"template_id": template_id, "reused": False}


def adopt_generated_docs(client: SuperDocsClient, conn,
                         pack_title: str) -> list[dict]:
    session_id = db.get_meta(conn, "session_id")
    known = {r["session_slot_id"] for r in conn.execute(
        "SELECT session_slot_id FROM documents").fetchall()}
    adopted = []
    for entry in client.roster(session_id):
        slot = entry.get("document_id")
        if not slot or slot in known:
            continue
        name = entry.get("name") or pack_title
        durable = entry.get("durable_document_id")
        conn.execute(
            "INSERT OR IGNORE INTO documents(session_slot_id,"
            " durable_document_id, role, name, version_hash, bound_at)"
            " VALUES(?,?,?,?,?,?)",
            (slot, durable, "generated", name, "", db.now()))
        adopted.append({"session_slot_id": slot, "durable_document_id":
                        durable, "name": name})
    conn.commit()
    return adopted


def pack_document_html(client: SuperDocsClient, conn, slot: str) -> str:
    session_id = db.get_meta(conn, "session_id")
    for entry in client.roster(session_id, include_html=True):
        if entry.get("document_id") == slot:
            return entry.get("html", "")
    raise RuntimeError(f"pack document {slot} vanished from roster")


def build_pack(client: SuperDocsClient, conn, template_path: str | None =
               None, out_dir: str = "exports", filename: str |
               None = None, formats: tuple = ("docx", "pdf"),
               library_path: str | None = None) -> dict:
    session_id = db.get_meta(conn, "session_id")
    if not session_id:
        raise RuntimeError("no session bound; run init first")

    template_info = ensure_template(client, conn, template_path)
    template_name = db.get_meta(conn, "pack_template_name") or "letterhead"

    matrix = collect_matrix(conn, library_path)
    stem = filename or "northgate-audit-readiness-pack"
    title = DEFAULT_TITLE
    prompt = render_prompt(matrix, template_name, title=title)

    ops_before = sum(u["ops_charged"] for u in client.usage_log)
    resp = client.chat_wait(prompt, session_id, latency_class="complex_edit")
    job_id = resp.get("job_id")
    if job_id:
        client.register_our_job(conn, job_id, "pack-generation")

    adopted = adopt_generated_docs(client, conn, title)
    if not adopted:
        raise RuntimeError("no new document appeared in the roster; the "
                           "generation turn may have failed silently")
    pack_doc = adopted[0]

    html = pack_document_html(client, conn, pack_doc["session_slot_id"])
    assert_language_rail(html)

    client.focus_document(session_id, pack_doc["session_slot_id"])

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    exports = []
    for fmt in formats:
        dl = client.request_download(session_id, fmt, filename=stem)
        warnings = client.export_warnings()
        target = out / f"{stem}.{fmt}"
        size = client.fetch_to_file(dl["download_url"], str(target))
        exports.append({"format": fmt, "path": str(target), "bytes": size,
                        "warnings": warnings})


    charged = sum(u["ops_charged"] for u in client.usage_log) - ops_before
    run_key = f"pack:{job_id or db.now()}"
    guards.mark_run(conn, run_key, "pack", charged)
    return {"document": pack_doc, "title": title, "run_key": run_key,
            "template": template_info, "exports": exports,
            "ops_spent": charged, "language_rail": "clean"}
