"""A deterministic stand-in for the SuperDocs API.

**Why this exists.** "A restart is invisible in the output" is only a provable claim if
the backend is constant. A language model is not: two runs of the same plan differ by
nature, so byte-identity against the live API would be unprovable, and asserting it
anyway would be theatre. This fake holds the backend still so that the only variable
left in the experiment is the runner — which is the thing actually under test.

**What it is not.** It is not a language model and does not pretend to be. It implements
a deterministic subset of editing — quoted directives inside the instruction text —
chosen to exercise every code path the real API exercises: multi-document sessions,
async jobs, HITL pauses with per-change approval, partial approval, export, session
history, and job expiry.

**What it deliberately does not do:** deduplicate. If the runner sends the same turn
twice, this server applies it twice and counts it twice. A fake that quietly swallowed
duplicates would hide the exact bug the at-most-once tests exist to catch.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response

STATE_DIR = Path(os.environ.get("FAKE_STATE_DIR", "./.fake-state"))
#: Seconds before a job is purged, mirroring the documented 1h job TTL. Tests set it
#: low to exercise the path where the fast reconciliation route is unavailable.
JOB_TTL = float(os.environ.get("FAKE_JOB_TTL", "3600"))

_lock = threading.RLock()
app = FastAPI(title="fake-superdocs")


# --- durable-ish state ----------------------------------------------------

def _state_path() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / "state.json"


def _blank() -> dict[str, Any]:
    return {"sessions": {}, "turn_counts": {}, "job_counter": 0, "chat_calls": 0,
            "billed": 0}


def _load() -> dict[str, Any]:
    p = _state_path()
    if not p.exists():
        return _blank()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _blank()


def _save(state: dict[str, Any]) -> None:
    p = _state_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def _session(state: dict[str, Any], session_id: str) -> dict[str, Any]:
    return state["sessions"].setdefault(
        session_id, {"documents": {}, "order": [], "focused": None, "messages": [], "jobs": {}}
    )


# --- deterministic ids ----------------------------------------------------

def _h(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


def _chunk_id(doc_id: str, ordinal: int) -> str:
    return f"ck_{_h(doc_id, str(ordinal))[:16]}"


def _change_id(doc_id: str, chunk_id: str, token: str, new_html: str) -> str:
    return f"ch_{_h(doc_id, chunk_id, token, new_html)[:16]}"


# --- the deterministic edit engine ----------------------------------------

_RE_REPLACE = re.compile(r'replace\s+"([^"]+)"\s+with\s+"([^"]+)"', re.I)
_RE_ADD = re.compile(r'add a section titled\s+"([^"]+)"\s+containing\s+"([^"]+)"', re.I)
_RE_REMOVE = re.compile(r'remove the section titled\s+"([^"]+)"', re.I)
_RE_TOKEN = re.compile(r"\[longhaul:\d+:[0-9a-f]+\]")


def _propose(doc: dict[str, Any], instruction: str, token: str) -> list[dict[str, Any]]:
    """Compute proposed changes. A pure function of (document, instruction)."""
    doc_id = doc["document_id"]
    changes: list[dict[str, Any]] = []

    for old, new in _RE_REPLACE.findall(instruction):
        for ordinal, chunk in enumerate(doc["chunks"]):
            if old in chunk["html"]:
                new_html = chunk["html"].replace(old, new)
                changes.append({
                    "change_id": _change_id(doc_id, chunk["chunk_id"], token, new_html),
                    "operation": "edit",
                    "chunk_id": chunk["chunk_id"],
                    "document_id": doc_id,
                    "old_html": chunk["html"],
                    "new_html": new_html,
                    "ai_explanation": f'Replaced "{old}" with "{new}".',
                })

    for title, _body in _RE_ADD.findall(instruction):
        new_html = f"<h2>{title}</h2>"
        last = doc["chunks"][-1]["chunk_id"] if doc["chunks"] else None
        changes.append({
            "change_id": _change_id(doc_id, f"new:{title}", token, new_html),
            "operation": "create",
            "chunk_id": None,
            "insert_after_chunk_id": last,
            "document_id": doc_id,
            "old_html": "",
            "new_html": new_html,
            "ai_explanation": f'Added a section titled "{title}".',
        })

    for title in _RE_REMOVE.findall(instruction):
        for chunk in doc["chunks"]:
            if title.lower() in chunk["html"].lower():
                changes.append({
                    "change_id": _change_id(doc_id, chunk["chunk_id"], token, ""),
                    "operation": "delete",
                    "chunk_id": chunk["chunk_id"],
                    "document_id": doc_id,
                    "old_html": chunk["html"],
                    "new_html": "",
                    "ai_explanation": f'Removed the section titled "{title}".',
                })
                break

    return changes


def _follow_up(doc: dict[str, Any], instruction: str, token: str) -> list[dict[str, Any]]:
    """The second round of a two-part edit.

    A single instruction can need more than one round of review: the model applies what
    was approved and then proposes the next part. The live API does exactly this for
    "add a section titled X containing Y" — heading first, paragraph second — and a
    stand-in that finished in one round would let that whole class of bug through.
    """
    doc_id = doc["document_id"]
    out = []
    for title, body in _RE_ADD.findall(instruction):
        new_html = f"<p>{body}</p>"
        out.append({
            "change_id": _change_id(doc_id, f"new-body:{title}", token, new_html),
            "operation": "create",
            "chunk_id": None,
            "insert_after_chunk_id": None,
            "document_id": doc_id,
            "old_html": "",
            "new_html": new_html,
            "ai_explanation": f'Added the body of the "{title}" section.',
        })
    return out


def _apply(doc: dict[str, Any], changes: list[dict[str, Any]]) -> None:
    """Apply approved changes in proposal order. Deterministic."""
    for ch in changes:
        op = ch["operation"]
        if op == "edit":
            for chunk in doc["chunks"]:
                if chunk["chunk_id"] == ch["chunk_id"]:
                    chunk["html"] = ch["new_html"]
                    break
        elif op == "delete":
            doc["chunks"] = [c for c in doc["chunks"] if c["chunk_id"] != ch["chunk_id"]]
        elif op == "create":
            ordinal = len(doc["chunks"]) + doc.get("created_count", 0)
            doc.setdefault("created_count", 0)
            doc["created_count"] += 1
            doc["chunks"].append({
                "chunk_id": _chunk_id(doc["document_id"], 10_000 + ordinal),
                "html": ch["new_html"],
            })
    doc["version"] = int(doc.get("version", 1)) + 1


def _doc_html(doc: dict[str, Any]) -> str:
    return "".join(
        f'<div data-chunk-id="{c["chunk_id"]}">{c["html"]}</div>' for c in doc["chunks"]
    )


# --- endpoints ------------------------------------------------------------

@app.get("/v1/sessions")
def list_sessions() -> dict[str, Any]:
    with _lock:
        state = _load()
        return {"sessions": [{"session_id": s} for s in sorted(state["sessions"])]}


@app.post("/v1/documents/upload")
async def upload(
    file: UploadFile,
    session_id: str = Form(...),
    open_mode: str = Form("replace"),
) -> dict[str, Any]:
    raw = (await file.read()).decode("utf-8", errors="replace")
    with _lock:
        state = _load()
        sess = _session(state, session_id)
        name = Path(file.filename or "document").stem
        doc_id = f"doc_{_h(session_id, name)[:16]}"

        if doc_id not in sess["documents"]:
            blocks = [b.strip() for b in raw.split("\n\n") if b.strip()]
            chunks = [
                {"chunk_id": _chunk_id(doc_id, i), "html": _blockify(b)}
                for i, b in enumerate(blocks)
            ]
            sess["documents"][doc_id] = {
                "document_id": doc_id, "title": name, "chunks": chunks, "version": 1,
            }
            sess["order"].append(doc_id)

        if open_mode in ("replace", "new_focused", "new_tab") or sess["focused"] is None:
            sess["focused"] = doc_id
        _save(state)
        doc = sess["documents"][doc_id]
        return {
            "document_id": doc_id,
            "html": _doc_html(doc),
            "chunks_count": len(doc["chunks"]),
            "version_id": f"v_{doc['version']}",
            "title": doc["title"],
            "session_id": session_id,
            "documents": _roster(sess),
        }


@app.post("/v1/chat/async")
def chat_async(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    session_id = payload["session_id"]
    message = payload["message"]
    with _lock:
        state = _load()
        sess = _session(state, session_id)

        # Count every turn by its idempotency token. This counter is the oracle the
        # at-most-once tests assert on — never the runner's own account of itself.
        m = _RE_TOKEN.search(message)
        token = m.group(0) if m else f"<untokened:{_h(message)[:8]}>"
        state["turn_counts"][token] = state["turn_counts"].get(token, 0) + 1
        state["chat_calls"] += 1

        state["job_counter"] += 1
        job_id = f"job_{state['job_counter']:05d}"

        # The live API refuses a new instruction while the session has changes staged
        # for review, and says so with a 409. Reproduced here because a stand-in that
        # accepted the turn would let a whole class of resume bug through untested.
        staged = next(
            (j for j in sess["jobs"].values() if j.get("status") == "awaiting_approval"),
            None,
        )
        if staged is not None:
            raise HTTPException(409, detail={
                "error_code": "session_busy",
                "message": "This conversation has changes waiting for your review, so it "
                           "can't take a new instruction yet.",
                "suggested_action": "Decide the staged changes with approve_change.",
            })

        doc_id = payload.get("document_id") or sess["focused"]
        doc = sess["documents"].get(doc_id)
        if doc is None:
            raise HTTPException(404, detail=f"no open document {doc_id}")

        sess["messages"].append({
            "turn_index": len(sess["messages"]),
            "role": "user",
            "content": message,
            "job_id": job_id,
        })

        changes = _propose(doc, message, token)
        # Nothing to propose is a real outcome, not a pause. Leaving a zero-change turn
        # parked in awaiting_approval would hang any client that waits for it.
        if not changes or payload.get("approval_mode") == "approve_all":
            _apply(doc, changes)
            job = _finish_job(job_id, session_id, doc, changes, state=state)
            sess["messages"].append({
                "turn_index": len(sess["messages"]), "role": "assistant",
                "content": f"Applied {len(changes)} changes.", "job_id": job_id,
            })
        else:
            job = {
                "job_id": job_id, "session_id": session_id, "status": "awaiting_approval",
                "created_at": time.time(), "document_id": doc_id,
                # JSON-encoded on purpose: the real API hands proposed-change content
                # back as a string that needs a second parse. Clients that miss it see
                # empty diff cards, so the fake reproduces the trap rather than hiding it.
                "metadata": {"awaiting_kind": "change_review",
                             "pending_changes": json.dumps(changes)},
                "result": None, "error": None, "_changes": changes,
                "_followup": _follow_up(doc, message, token),
            }
        sess["jobs"][job_id] = job
        _save(state)
        return {"job_id": job_id, "session_id": session_id, "status": job["status"]}


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    with _lock:
        state = _load()
        for sess in state["sessions"].values():
            job = sess["jobs"].get(job_id)
            if job is None:
                continue
            if time.time() - job.get("created_at", 0) > JOB_TTL:
                # Mirrors the documented purge. Reconciliation must not depend on this.
                raise HTTPException(404, detail="job expired")
            return {k: v for k, v in job.items() if not k.startswith("_")}
    raise HTTPException(404, detail="job not found")


@app.post("/v1/chat/{session_id}/approve")
def approve(session_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if "approved" not in payload:
        # The real API answers 422 here. Reproduced so the client is tested against it.
        raise HTTPException(422, detail="top-level 'approved' is required")
    with _lock:
        state = _load()
        sess = _session(state, session_id)
        job = sess["jobs"].get(payload["job_id"])
        if job is None:
            raise HTTPException(404, detail="job not found")

        entries = payload.get("changes")
        if entries is None:
            entries = [{"change_id": payload.get("change_id"), "approved": payload["approved"]}]
        decisions = {
            e["change_id"]: bool(e.get("approved", payload["approved"])) for e in entries
        }

        if job["status"] == "awaiting_approval":
            proposed = job.get("_changes", [])
            approved = [c for c in proposed if decisions.get(c["change_id"], False)]
            doc = sess["documents"][job["document_id"]]
            _apply(doc, approved)

            followup = job.get("_followup") or []
            if followup and approved:
                # Same turn, another round: the job goes back to awaiting_approval with
                # changes the caller has not seen yet.
                job["status"] = "awaiting_approval"
                job["metadata"] = {"awaiting_kind": "change_review",
                                   "pending_changes": json.dumps(followup)}
                job["_changes"] = followup
                job["_followup"] = []
                sess["jobs"][payload["job_id"]] = job
                _save(state)
                return {"status": "ok", "job_id": payload["job_id"],
                        "job_status": "awaiting_approval"}

            sess["jobs"][payload["job_id"]] = _finish_job(
                payload["job_id"], session_id, doc, approved,
                proposed=len(proposed), state=state,
            )
            sess["messages"].append({
                "turn_index": len(sess["messages"]), "role": "assistant",
                "content": f"Applied {len(approved)} of {len(proposed)} proposed changes.",
                "job_id": payload["job_id"],
            })
            _save(state)
        # Replaying an approve on a settled job is a no-op that returns the same result:
        # the decisions name changes that already exist, so there is nothing new to apply.
        return {"status": "ok", "job_id": payload["job_id"],
                "job_status": sess["jobs"][payload["job_id"]]["status"]}


@app.post("/v1/documents/export")
def export(payload: dict[str, Any] = Body(...)) -> Response:
    fmt = payload.get("format", "docx")
    with _lock:
        state = _load()
        if payload.get("html") is not None:
            body = _render(payload["html"], fmt)
        else:
            # The real endpoint has no per-document selector: exporting by session_id
            # always returns the *focused* document, and a document_id in the payload is
            # accepted and ignored. Reproduced deliberately — a stand-in that honoured it
            # hid a real bug, which then only surfaced against the live API.
            sess = _session(state, payload["session_id"])
            doc = sess["documents"].get(sess["focused"])
            if doc is None:
                raise HTTPException(404, detail="no such document")
            body = _render(_doc_html(doc), fmt)
    # No timestamps, no compression metadata, no nondeterministic headers: the bytes are
    # a pure function of the document. Real .docx carries a creation time and could never
    # be byte-identical across two runs; see README, "What is proven and what is not".
    return Response(content=body, media_type="application/octet-stream")


@app.get("/v1/sessions/{session_id}/history")
def history(
    session_id: str, include_document_html: str = Query("false")
) -> dict[str, Any]:
    with _lock:
        state = _load()
        sess = _session(state, session_id)
        out: dict[str, Any] = {"session_id": session_id, "messages": sess["messages"]}
        if include_document_html.lower() == "true" and sess["focused"]:
            doc = sess["documents"][sess["focused"]]
            out["document_state"] = {"html": _doc_html(doc), "version": doc["version"]}
        return out


@app.get("/v1/sessions/{session_id}/jobs")
def session_jobs(session_id: str) -> dict[str, Any]:
    with _lock:
        state = _load()
        sess = _session(state, session_id)
        live = [
            {k: v for k, v in job.items() if not k.startswith("_")}
            for job in sess["jobs"].values()
            if time.time() - job.get("created_at", 0) <= JOB_TTL
        ]
        live.sort(key=lambda j: j["job_id"], reverse=True)
        return {"jobs": live}


@app.get("/v1/sessions/{session_id}/documents")
def session_documents(session_id: str, include_html: str = Query("false")) -> dict[str, Any]:
    with _lock:
        state = _load()
        sess = _session(state, session_id)
        return {"documents": _roster(sess, include_html.lower() == "true")}


# --- test-only introspection ---------------------------------------------
# Not part of the SuperDocs API. The proof suite reads these to assert on what the
# server actually received, rather than trusting the runner's self-report.

@app.get("/_test/stats")
def stats() -> dict[str, Any]:
    with _lock:
        state = _load()
        return {
            "turn_counts": state["turn_counts"],
            "chat_calls": state["chat_calls"],
            "duplicate_turns": {k: v for k, v in state["turn_counts"].items() if v > 1},
        }


@app.get("/_test/documents/{session_id}")
def test_documents(session_id: str) -> dict[str, Any]:
    with _lock:
        state = _load()
        sess = _session(state, session_id)
        return {
            doc_id: {"html": _doc_html(d), "version": d["version"], "title": d["title"]}
            for doc_id, d in sorted(sess["documents"].items())
        }


@app.exception_handler(HTTPException)
def _http_error(_r: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# --- helpers --------------------------------------------------------------

def _finish_job(
    job_id: str, session_id: str, doc: dict[str, Any], applied: list[dict[str, Any]],
    *, proposed: int | None = None, state: dict[str, Any] | None = None
) -> dict[str, Any]:
    billable = bool(proposed if proposed is not None else applied)
    limit = int(os.environ.get("FAKE_MONTHLY_LIMIT", "500"))
    if state is not None and billable:
        state["billed"] = state.get("billed", 0) + 1
    used = (state or {}).get("billed", 0)
    return {
        "job_id": job_id, "session_id": session_id, "status": "completed",
        "created_at": time.time(), "document_id": doc["document_id"],
        "metadata": {}, "error": None,
        "result": {
            "response": f"Applied {len(applied)} changes.",
            "session_id": session_id,
            "document_changes": {
                "updated_html": _doc_html(doc),
                "version_id": f"v_{doc['version']}",
                "changes_summary": f"{len(applied)} sections updated",
            },
            # A turn that proposed nothing is not billed for the edit it never made.
            "usage": {
                "was_billable": billable,
                "monthly_used": used,
                "monthly_limit": limit,
                "monthly_remaining": max(0, limit - used),
                "subscription_tier": "free",
            },
        },
    }


def _roster(sess: dict[str, Any], include_html: bool = False) -> list[dict[str, Any]]:
    out = []
    for doc_id in sess["order"]:
        doc = sess["documents"][doc_id]
        entry = {
            "document_id": doc_id, "title": doc["title"],
            "focused": doc_id == sess["focused"], "chunks_count": len(doc["chunks"]),
        }
        if include_html:
            entry["html"] = _doc_html(doc)
        out.append(entry)
    return out


def _blockify(block: str) -> str:
    stripped = block.strip()
    if stripped.startswith("### "):
        return f"<h3>{stripped[4:]}</h3>"
    if stripped.startswith("## "):
        return f"<h2>{stripped[3:]}</h2>"
    if stripped.startswith("# "):
        return f"<h1>{stripped[2:]}</h1>"
    return f"<p>{stripped}</p>"


_TAG = re.compile(r"<[^>]+>")


def _render(html: str, fmt: str) -> bytes:
    if fmt in ("html", "docx", "doc"):
        return html.encode("utf-8")
    text = _TAG.sub("\n", html)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return ("\n".join(lines) + "\n").encode("utf-8")


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("FAKE_PORT", "8099")),
        log_level="warning",
    )
