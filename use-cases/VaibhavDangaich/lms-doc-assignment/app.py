"""lms-doc-assignment — an LTI 1.3 tool that launches a SuperDocs track-changes review
inside Canvas or Moodle, and posts a completion grade back through AGS.

Canvas and Moodle don't share a REST API; the shape both platforms actually speak is LTI
1.3: an OIDC third-party-initiated login, a signed JWT launch request the tool verifies
against the platform's own public keys, Deep Linking so an instructor can place a "review
this document" assignment into the course, and Assignment and Grade Services (AGS) to post
a completion grade back to the gradebook once review is done.

This file is the whole tool. Four LTI-side routes (login, launch, jwks, deep-link
configure) plus a small review surface backed by SuperDocs' real chat/approve API — the
same track-changes HITL flow ("ask_every_time" approval mode) a human reviewer would use
directly in the product, just launched from inside an LMS assignment instead of the
SuperDocs web app.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from tempfile import mkdtemp

import requests
from flask import Flask, jsonify, render_template, request
from flask_caching import Cache
from pylti1p3.contrib.flask import (
    FlaskCacheDataStorage,
    FlaskMessageLaunch,
    FlaskOIDCLogin,
    FlaskRequest,
)
from pylti1p3.deep_link_resource import DeepLinkResource
from pylti1p3.grade import Grade
from pylti1p3.lineitem import LineItem
from pylti1p3.tool_config import ToolConfJsonFile
from werkzeug.exceptions import Forbidden

from documents.catalog import DOCUMENTS, get_document

app = Flask(__name__, template_folder="templates")
app.config.from_mapping(
    {
        # Werkzeug's debugger is an unauthenticated eval console; this tool handles signed
        # launch JWTs, so it stays off even in local dev. Flask's own reloader/tracebacks
        # still work fine without it.
        "DEBUG": False,
        "CACHE_TYPE": "simple",
        "CACHE_DEFAULT_TIMEOUT": 3600,
        "SECRET_KEY": os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me"),
        "SESSION_TYPE": "filesystem",
        "SESSION_FILE_DIR": mkdtemp(),
        "SESSION_COOKIE_NAME": "lms-doc-assignment-session",
        "SESSION_COOKIE_HTTPONLY": True,
        # False here because local Moodle/Canvas testing runs over plain HTTP (see README);
        # set True + SAMESITE="None" behind real HTTPS.
        "SESSION_COOKIE_SECURE": False,
        "SESSION_COOKIE_SAMESITE": None,
    }
)
cache = Cache(app)

SUPERDOCS_BASE_URL = os.environ.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app")
SUPERDOCS_API_KEY = os.environ.get("SUPERDOCS_API_KEY")

# Per-launch review state: superdocs session id, current job/change awaiting a decision,
# and whether review has been marked complete. In-memory by design — this is a demo tool,
# not a production gradebook system, and it's noted as such in the README.
_REVIEW_STATE: dict[str, dict] = {}


def get_lti_config_path() -> str:
    return os.path.join(app.root_path, "configs", "tool.json")


def get_launch_data_storage() -> FlaskCacheDataStorage:
    return FlaskCacheDataStorage(cache)


def _superdocs_headers() -> dict[str, str]:
    if not SUPERDOCS_API_KEY:
        raise RuntimeError(
            "SUPERDOCS_API_KEY is not set. Fix: export SUPERDOCS_API_KEY=sk_... "
            "before starting this app."
        )
    return {"Authorization": f"Bearer {SUPERDOCS_API_KEY}"}


# ── LTI 1.3 core: login, launch, jwks ─────────────────────────────────────────


@app.route("/login/", methods=["GET", "POST"])
def login():
    tool_conf = ToolConfJsonFile(get_lti_config_path())
    launch_data_storage = get_launch_data_storage()
    flask_request = FlaskRequest()
    target_link_uri = flask_request.get_param("target_link_uri")
    if not target_link_uri:
        raise Exception('Missing "target_link_uri" param')
    oidc_login = FlaskOIDCLogin(flask_request, tool_conf, launch_data_storage=launch_data_storage)
    return oidc_login.enable_check_cookies().redirect(target_link_uri)


@app.route("/launch/", methods=["POST"])
def launch():
    tool_conf = ToolConfJsonFile(get_lti_config_path())
    flask_request = FlaskRequest()
    launch_data_storage = get_launch_data_storage()
    message_launch = FlaskMessageLaunch(flask_request, tool_conf, launch_data_storage=launch_data_storage)
    launch_data = message_launch.get_launch_data()
    launch_id = message_launch.get_launch_id()

    if message_launch.is_deep_link_launch():
        return render_template("deep_link_pick.html", launch_id=launch_id, documents=DOCUMENTS)

    # Resource-link launch: an instructor already placed this via deep linking, so a doc_id
    # rides the custom claim set at placement time (see /configure/ below).
    custom = launch_data.get("https://purl.imsglobal.org/spec/lti/claim/custom", {})
    doc_id = custom.get("doc_id")
    doc = get_document(doc_id) if doc_id else None
    if not doc:
        return "This assignment was not placed with a document selected. Fix: re-place it via Deep Linking.", 400

    _REVIEW_STATE.setdefault(
        launch_id,
        {"doc_id": doc_id, "superdocs_session_id": None, "pending": None, "complete": False},
    )
    return render_template(
        "review.html",
        launch_id=launch_id,
        doc_title=doc["title"],
        doc_html=doc["html"],
        user_name=launch_data.get("name", "reviewer"),
        has_ags=message_launch.has_ags(),
    )


@app.route("/jwks/", methods=["GET"])
def jwks():
    # get_jwks() already returns the full {"keys": [...]} shape - verified directly
    # against the installed pylti1p3 version, not assumed from an older example.
    tool_conf = ToolConfJsonFile(get_lti_config_path())
    return jsonify(tool_conf.get_jwks())


# ── Deep Linking: an instructor places "review this document" into the course ─


@app.route("/configure/<launch_id>/<doc_id>/", methods=["POST"])
def configure(launch_id: str, doc_id: str):
    tool_conf = ToolConfJsonFile(get_lti_config_path())
    flask_request = FlaskRequest()
    launch_data_storage = get_launch_data_storage()
    message_launch = FlaskMessageLaunch.from_cache(
        launch_id, flask_request, tool_conf, launch_data_storage=launch_data_storage
    )
    if not message_launch.is_deep_link_launch():
        raise Forbidden("Must be a deep link launch")

    doc = get_document(doc_id)
    if not doc:
        raise Forbidden(f"Unknown document id: {doc_id}")

    resource = DeepLinkResource()
    # Deliberately no .set_url() here. A content item that carries its own url makes
    # Moodle's content_item_to_form() bind the placement to typeid=0 (a legacy ad-hoc-URL
    # launch), not this registered LTI Advantage tool - so the resulting course module
    # launches over LTI 1.1 with no AGS claim at all, silently. Leaving url unset makes
    # Moodle fall back to the tool's own registered launch URL (lti_toolurl in
    # register_tool.php - the exact same http://localhost:9001/launch/), while binding
    # typeid to this tool's real id. Found by tracing a launch that landed on
    # "Missing state param" back through a decoded JWT that had lti-bo/claim/basicoutcome
    # instead of an AGS claim.
    resource.set_custom_params({"doc_id": doc_id})
    resource.set_title(f"Review: {doc['title']}")

    html = message_launch.get_deep_link().output_response_form([resource])
    return html


# ── Review flow, backed by SuperDocs' real chat + approve API ────────────────


def _get_state(launch_id: str) -> dict:
    state = _REVIEW_STATE.get(launch_id)
    if not state:
        raise Forbidden("Unknown or expired launch. Fix: relaunch the assignment from the LMS.")
    return state


@app.route("/api/review/<launch_id>/edit", methods=["POST"])
def review_edit(launch_id: str):
    """Send an edit instruction to SuperDocs with approval_mode='ask_every_time' — the
    same human-in-the-loop mode the product itself uses for regulated review workflows.
    Polls briefly for the first pending change or completion and returns it."""
    state = _get_state(launch_id)
    instruction = request.json.get("instruction", "").strip()
    if not instruction:
        return jsonify({"error": "instruction is required"}), 400

    doc = get_document(state["doc_id"])
    session_id = state["superdocs_session_id"] or f"lms-{launch_id}"
    body = {
        "message": instruction,
        "session_id": session_id,
        "async_mode": True,
        "approval_mode": "ask_every_time",
        "response_mode": "compact",
    }
    if not state["superdocs_session_id"]:
        body["document_html"] = doc["html"]

    resp = requests.post(
        f"{SUPERDOCS_BASE_URL}/v1/chat/async", headers=_superdocs_headers(), json=body, timeout=30
    )
    if resp.status_code >= 400:
        return jsonify({"error": resp.text}), 502
    job_id = resp.json()["job_id"]
    state["superdocs_session_id"] = session_id

    job = _poll_job(job_id)
    return jsonify(_summarize_job(state, job))


@app.route("/api/review/<launch_id>/decide", methods=["POST"])
def review_decide(launch_id: str):
    """Approve or deny the pending change, then resume polling until the job settles."""
    state = _get_state(launch_id)
    pending = state.get("pending")
    if not pending:
        return jsonify({"error": "nothing pending"}), 400

    approved = bool(request.json.get("approved"))
    resp = requests.post(
        f"{SUPERDOCS_BASE_URL}/v1/chat/{state['superdocs_session_id']}/approve",
        headers=_superdocs_headers(),
        json={"job_id": pending["job_id"], "change_id": pending["change_id"], "approved": approved},
        timeout=30,
    )
    if resp.status_code >= 400:
        return jsonify({"error": resp.text}), 502

    job = _poll_job(pending["job_id"])
    return jsonify(_summarize_job(state, job))


@app.route("/api/review/<launch_id>/complete", methods=["POST"])
def review_complete(launch_id: str):
    """Mark the review done and post the completion grade back through AGS — the actual
    gradebook write, not a status flag the LMS never sees."""
    state = _get_state(launch_id)
    tool_conf = ToolConfJsonFile(get_lti_config_path())
    flask_request = FlaskRequest()
    launch_data_storage = get_launch_data_storage()
    message_launch = FlaskMessageLaunch.from_cache(
        launch_id, flask_request, tool_conf, launch_data_storage=launch_data_storage
    )
    if not message_launch.has_ags():
        return jsonify({"error": "This platform did not grant grade services for this launch."}), 400

    launch_data = message_launch.get_launch_data()
    sub = launch_data.get("sub")
    resource_link_id = launch_data.get(
        "https://purl.imsglobal.org/spec/lti/claim/resource_link", {}
    ).get("id")

    grade = Grade()
    grade.set_score_given(1).set_score_maximum(1).set_activity_progress("Completed").set_grading_progress(
        "FullyGraded"
    ).set_user_id(sub).set_timestamp(
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    )

    line_item = LineItem()
    line_item.set_tag("document_review").set_score_maximum(1).set_label("Document Review Complete")
    if resource_link_id:
        line_item.set_resource_id(resource_link_id)

    result = message_launch.get_ags().put_grade(grade, line_item)
    state["complete"] = True
    return jsonify({"success": True, "ags_result": result.get("body")})


def _poll_job(job_id: str, attempts: int = 15, delay: float = 1.0) -> dict:
    """Polls compact (cheap) while the job runs. compact=true nulls out
    metadata.pending_changes even once status reaches awaiting_approval - the API's own
    docs only warn about this for 'completed', not 'awaiting_approval', so this was found
    empirically, not from the docs (see README's rough-edges section). One extra
    non-compact fetch on either terminal status gets the real diff/result back."""
    import time

    for _ in range(attempts):
        resp = requests.get(
            f"{SUPERDOCS_BASE_URL}/v1/jobs/{job_id}",
            headers=_superdocs_headers(),
            params={"compact": True},
            timeout=30,
        )
        resp.raise_for_status()
        job = resp.json()
        status = job.get("status")
        if status in ("completed", "awaiting_approval"):
            resp = requests.get(
                f"{SUPERDOCS_BASE_URL}/v1/jobs/{job_id}", headers=_superdocs_headers(), timeout=30
            )
            resp.raise_for_status()
            return resp.json()
        if status in ("failed", "cancelled"):
            return job
        time.sleep(delay)
    return job


def _summarize_job(state: dict, job: dict) -> dict:
    status = job.get("status")
    pending_changes = (job.get("metadata") or {}).get("pending_changes") or []
    if status == "awaiting_approval" and pending_changes:
        change = pending_changes[0]
        state["pending"] = {"job_id": job["job_id"], "change_id": change.get("change_id")}
    else:
        state["pending"] = None
    return {
        "status": status,
        "pending_change": pending_changes[0] if pending_changes else None,
        "response": job.get("result", {}).get("response") if job.get("result") else None,
    }


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9001)
