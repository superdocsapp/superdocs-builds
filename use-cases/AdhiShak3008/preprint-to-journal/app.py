"""
app.py
Preprint to Journal Submission Converter
Flask web application — server-side only, API key never reaches the browser.

State is held in an in-memory dict keyed by a browser session UUID.
This is appropriate for a demo; a production deployment would use a
persistent store.
"""

import os
import uuid
import json
from flask import (
    Flask, request, jsonify, render_template,
    session, send_file, redirect, url_for
)
import io

import superdocs_client as sd
from journal_loader import load_profile, list_profiles, JournalProfileError
from instruction_builder import build_instruction
from preservation_checker import check_preservation
from blinding import analyse_blinding
from compliance_reporter import build_report, summarise_report

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

# In-memory state store: { browser_session_id -> state_dict }
# State dict keys:
#   original_html        - immutable original manuscript HTML
#   original_filename    - uploaded filename
#   conversion_sessions  - { journal_id -> { session_id, job_id, status, ... } }
#   current_journal_id   - currently selected journal
_state = {}


def _get_state():
    sid = session.get("sid")
    if not sid or sid not in _state:
        sid = str(uuid.uuid4())
        session["sid"] = sid
        _state[sid] = {
            "original_html": None,
            "original_filename": None,
            "conversion_sessions": {},
            "current_journal_id": None,
        }
    return _state[sid]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    journals = list_profiles()
    state = _get_state()
    return render_template(
        "index.html",
        journals=journals,
        has_manuscript=bool(state.get("original_html")),
        original_filename=state.get("original_filename"),
    )


@app.route("/review")
def review():
    state = _get_state()
    journal_id = state.get("current_journal_id")
    if not journal_id or not state.get("original_html"):
        return redirect(url_for("index"))
    try:
        profile = load_profile(journal_id)
    except JournalProfileError as e:
        return render_template("index.html", error=str(e), journals=list_profiles())

    conv = state["conversion_sessions"].get(journal_id, {})
    return render_template(
        "review.html",
        journal=profile,
        conv=conv,
        job_id=conv.get("job_id"),
        session_id=conv.get("session_id"),
    )


@app.route("/report")
def report():
    state = _get_state()
    journal_id = state.get("current_journal_id")
    if not journal_id:
        return redirect(url_for("index"))
    conv = state["conversion_sessions"].get(journal_id, {})
    compliance = conv.get("compliance_report", [])
    preservation = conv.get("preservation_result", {})
    blinding_result = conv.get("blinding_result")
    try:
        profile = load_profile(journal_id)
    except JournalProfileError:
        return redirect(url_for("index"))
    summary = summarise_report(compliance)
    return render_template(
        "report.html",
        journal=profile,
        compliance=compliance,
        summary=summary,
        preservation=preservation,
        blinding_result=blinding_result,
        can_export=bool(conv.get("session_id") and conv.get("status") == "completed"),
    )


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Upload a manuscript DOCX. Stores original HTML in state."""
    if "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No filename."}), 400
    if not f.filename.lower().endswith(".docx"):
        return jsonify({"error": "Only .docx files are supported."}), 400

    state = _get_state()
    # Each upload gets a fresh SuperDocs session for the original
    upload_session_id = f"ptj-orig-{uuid.uuid4().hex[:12]}"
    try:
        result = sd.upload_document(f.read(), f.filename, upload_session_id)
    except sd.SuperDocsError as e:
        return jsonify({"error": str(e)}), 502

    original_html = result.get("html", "")
    state["original_html"] = original_html
    state["original_filename"] = f.filename
    state["conversion_sessions"] = {}  # reset conversions on new upload
    state["current_journal_id"] = None

    return jsonify({
        "ok": True,
        "filename": f.filename,
        "chunks_count": result.get("chunks_count", 0),
    })


@app.route("/api/transform", methods=["POST"])
def api_transform():
    """
    Start a transformation job for the selected journal.
    Always uses the original manuscript HTML — never a previously
    transformed version.
    """
    data = request.get_json() or {}
    journal_id = data.get("journal_id")
    author_names = data.get("author_names", [])
    author_affiliations = data.get("author_affiliations", [])

    if not journal_id:
        return jsonify({"error": "journal_id is required."}), 400

    state = _get_state()
    if not state.get("original_html"):
        return jsonify({"error": "No manuscript uploaded."}), 400

    try:
        profile = load_profile(journal_id)
    except JournalProfileError as e:
        return jsonify({"error": str(e)}), 400

    author_info = None
    if author_names or author_affiliations:
        author_info = {
            "names": author_names,
            "affiliations": author_affiliations,
        }

    instruction = build_instruction(profile, author_info)

    # Fresh SuperDocs session for this journal conversion
    conv_session_id = f"ptj-{journal_id}-{uuid.uuid4().hex[:12]}"

    try:
        job_id = sd.start_transformation(
            session_id=conv_session_id,
            document_html=state["original_html"],  # always the original
            instruction=instruction,
        )
    except sd.SuperDocsError as e:
        return jsonify({"error": str(e)}), 502

    state["current_journal_id"] = journal_id
    state["conversion_sessions"][journal_id] = {
        "session_id": conv_session_id,
        "job_id": job_id,
        "status": "in_progress",
        "pending_changes": [],
        "transformed_html": None,
        "compliance_report": [],
        "preservation_result": {},
        "blinding_result": None,
        "author_info": author_info,
    }

    return jsonify({
        "ok": True,
        "job_id": job_id,
        "session_id": conv_session_id,
    })


@app.route("/api/poll/<job_id>", methods=["GET"])
def api_poll(job_id):
    """Poll a transformation job for status updates."""
    state = _get_state()
    journal_id = state.get("current_journal_id")
    conv = state["conversion_sessions"].get(journal_id, {})

    if conv.get("job_id") != job_id:
        return jsonify({"error": "Job not found in current session."}), 404

    try:
        job_state = sd.poll_job(job_id)
    except sd.SuperDocsError as e:
        return jsonify({"error": str(e)}), 502

    status = job_state["status"]
    conv["status"] = status

    if status == "awaiting_approval":
        conv["pending_changes"] = job_state["pending_changes"]
        return jsonify({
            "status": "awaiting_approval",
            "pending_changes": job_state["pending_changes"],
        })

    if status == "completed":
        result = job_state.get("result") or {}
        transformed_html = sd.get_final_html(result) or ""
        conv["transformed_html"] = transformed_html

        # Build preservation check
        preservation = check_preservation(
            state["original_html"], transformed_html
        )
        conv["preservation_result"] = preservation

        # Build blinding analysis if applicable
        try:
            profile = load_profile(journal_id)
        except JournalProfileError:
            profile = {}

        blinding_result = None
        if profile.get("blinded_review") and transformed_html:
            blinding_result = analyse_blinding(
                transformed_html, conv.get("author_info")
            )
        conv["blinding_result"] = blinding_result

        # Build compliance report
        compliance = build_report(profile, transformed_html, blinding_result)
        conv["compliance_report"] = compliance

        return jsonify({
            "status": "completed",
            "has_concerns": preservation.get("has_concerns", False),
        })

    if status == "failed":
        return jsonify({
            "status": "failed",
            "error": job_state.get("error", "Unknown error"),
        })

    # in_progress / pending / cancelled
    return jsonify({"status": status})


@app.route("/api/approve", methods=["POST"])
def api_approve():
    """Submit per-change approval decisions."""
    data = request.get_json() or {}
    job_id = data.get("job_id")
    session_id = data.get("session_id")
    decisions = data.get("decisions", [])

    if not job_id or not session_id:
        return jsonify({"error": "job_id and session_id are required."}), 400

    try:
        sd.approve_changes(session_id, job_id, decisions)
    except sd.SuperDocsError as e:
        return jsonify({"error": str(e)}), 502

    return jsonify({"ok": True})


@app.route("/api/export", methods=["POST"])
def api_export():
    """Export the transformed manuscript as DOCX."""
    state = _get_state()
    journal_id = state.get("current_journal_id")
    conv = state["conversion_sessions"].get(journal_id, {})

    if conv.get("status") != "completed":
        return jsonify({"error": "Transformation not yet complete."}), 400

    session_id = conv.get("session_id")
    if not session_id:
        return jsonify({"error": "No active conversion session."}), 400

    original_name = state.get("original_filename", "manuscript").replace(".docx", "")
    export_name = f"{original_name}_{journal_id}"

    try:
        docx_bytes = sd.export_document(session_id, filename=export_name)
    except sd.SuperDocsError as e:
        return jsonify({"error": str(e)}), 502

    return send_file(
        io.BytesIO(docx_bytes),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=f"{export_name}.docx",
    )


@app.route("/api/journals", methods=["GET"])
def api_journals():
    return jsonify(list_profiles())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
