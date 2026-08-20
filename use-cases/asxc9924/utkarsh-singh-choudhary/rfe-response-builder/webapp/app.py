"""
Flask web UI around the rfe_response_builder package.

- GET  /            upload form (notice, petition JSON, optional evidence JSON,
                     case id, client name, dry-run checkbox)
- POST /generate     runs plan_response() (dry run, no API key / no network calls)
                     or build_response_packet() (real run, needs SUPERDOCS_API_KEY)
                     and either shows results inline (dry run) or streams the
                     generated .docx back as a download (real run).

Nothing in rfe_response_builder/ is modified -- this only imports and calls it.

Production hardening applied here (all scoped to this file -- the domain
package stays network-/framework-free):
  - trusts Render's reverse proxy for client IP/scheme (ProxyFix) so rate
    limiting, request.remote_addr, and url_for(_external) behave correctly
  - refuses to boot with the placeholder secret key unless explicitly
    allowed for local dev (FLASK_SECRET_KEY must be set in production)
  - CSRF protection on the POST /generate form
  - per-IP rate limiting on /generate (real runs spend SuperDocs operations
    and shell out to a third-party API -- this is the endpoint worth
    protecting from abuse/retries-gone-wild)
  - upload validation by extension, not just size (MAX_CONTENT_LENGTH
    already caps size at the WSGI layer)
  - security response headers (nosniff, no framing, referrer trimming)
  - explicit error handlers for 400/413/429/500 instead of default HTML
  - session_id built from the *sanitized* case id, and generate() catches
    the ValueError sanitize_case_id raises for garbage input
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from review_store import ReviewSessionStore
from werkzeug.middleware.proxy_fix import ProxyFix

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rfe_response_builder.generate import plan_response
from rfe_response_builder.review import finalize_review, start_review
from rfe_response_builder.rfe import (
    NewEvidenceCatalog,
    NewEvidenceEntry,
    PetitionArgument,
    PriorPetition,
    arguments_from_free_text,
    sanitize_case_id,
)
from rfe_response_builder.superdocs_client import SuperDocsClient, SuperDocsError

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("rfe_response_builder.webapp")

IS_PRODUCTION = os.environ.get("RENDER") is not None or os.environ.get("FLASK_ENV") == "production"
_DEV_SECRET = "dev-secret-change-me"

app = Flask(__name__)

secret_key = os.environ.get("FLASK_SECRET_KEY", _DEV_SECRET)
if secret_key == _DEV_SECRET and IS_PRODUCTION:
    # Fail loudly at boot rather than silently signing session/CSRF cookies
    # with a key that's sitting in this file on GitHub. render.yaml sets
    # FLASK_SECRET_KEY via generateValue, so this should never trip on Render
    # unless someone strips that out of the blueprint.
    raise RuntimeError(
        "FLASK_SECRET_KEY is not set. Refusing to start with the default "
        "dev secret in a production environment (RENDER or FLASK_ENV=production "
        "is set). Set FLASK_SECRET_KEY to a random value."
    )
app.secret_key = secret_key

# Render terminates TLS and proxies plain HTTP to the app with
# X-Forwarded-* headers set -- trust exactly one hop of each so
# request.remote_addr (rate limiting) and generated https:// URLs are correct.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
)

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "5"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

ALLOWED_EXTENSIONS = {
    "notice": {".txt"},
    "petition": {".json"},
    "evidence": {".json"},
    "supporting_docs": {".txt"},
}

# --- Review-session store -----------------------------------------------------
# Real runs now always go through a human-review gate (start_review /
# finalize_review) instead of drafting-and-exporting in one shot, per the
# "proposed changes wait for a human yes" requirement. That means the
# in-progress ReviewSession has to survive between the POST that starts a
# review and the POST that finalizes it. Backed by SQLite (review_store.py)
# rather than an in-memory dict so it's visible across gunicorn worker
# processes on this Render instance -- see review_store.py's module
# docstring for exactly what this does and doesn't solve.
_review_store = ReviewSessionStore()


def _store_review_session(session) -> str:
    review_id = uuid.uuid4().hex
    _review_store.put(review_id, session)
    return review_id


def _get_review_session(review_id: str):
    return _review_store.get(review_id)


def _delete_review_session(review_id: str) -> None:
    _review_store.delete(review_id)

# --- CSRF protection ---------------------------------------------------------
try:
    from flask_wtf import CSRFProtect

    csrf = CSRFProtect(app)
except ImportError:  # pragma: no cover - only hit if flask-wtf isn't installed
    csrf = None
    logger.warning("flask-wtf not installed -- CSRF protection is DISABLED. "
                    "Install flask-wtf (see webapp/requirements.txt) before deploying.")

# --- Rate limiting ------------------------------------------------------------
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri="memory://")
except ImportError:  # pragma: no cover - only hit if flask-limiter isn't installed
    limiter = None
    logger.warning("flask-limiter not installed -- rate limiting is DISABLED. "
                    "Install flask-limiter (see webapp/requirements.txt) before deploying.")


def _rate_limit(limit_str: str):
    """No-op decorator when flask-limiter isn't available, so the app still
    runs (with a loud warning above) instead of failing to import."""
    if limiter is None:
        return lambda f: f
    return limiter.limit(limit_str)


@app.after_request
def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'"
    if IS_PRODUCTION:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def _load_petition_from_text(raw_text: str) -> PriorPetition:
    raw = json.loads(raw_text)
    if not isinstance(raw, dict) or not isinstance(raw.get("arguments"), list):
        raise ValueError("petition file must be a JSON object with an 'arguments' array")
    return PriorPetition(
        arguments=[
            PetitionArgument(topic_id=a["topic_id"], text=a["text"], source_ref=a["source_ref"])
            for a in raw["arguments"]
        ]
    )


def _load_evidence_catalog_from_text(raw_text: str | None) -> NewEvidenceCatalog:
    if not raw_text:
        return NewEvidenceCatalog()
    raw = json.loads(raw_text)
    if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
        raise ValueError("evidence file must be a JSON object with an 'entries' array")
    return NewEvidenceCatalog(
        entries=[
            NewEvidenceEntry(
                topic_id=e["topic_id"], description=e["description"], exhibit_label=e["exhibit_label"]
            )
            for e in raw["entries"]
        ]
    )


def _read_upload(field_name: str) -> str | None:
    """Reads an uploaded field as UTF-8 text, validating its extension
    against ALLOWED_EXTENSIONS and rejecting anything that isn't valid
    UTF-8 (e.g. someone uploading a .docx renamed to .txt) with a clear
    error instead of an unhandled UnicodeDecodeError turning into a 500."""
    f = request.files.get(field_name)
    if f is None or f.filename == "":
        return None
    ext = Path(f.filename).suffix.lower()
    allowed = ALLOWED_EXTENSIONS.get(field_name, set())
    if ext not in allowed:
        raise ValueError(f"'{field_name}' must be one of {sorted(allowed)}, got '{ext or f.filename}'")
    try:
        return f.read().decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"'{field_name}' is not a valid UTF-8 text file") from e


def _read_supporting_docs() -> list[PetitionArgument]:
    """Multi-document ingestion: any number of free-text supporting
    documents (petition letter, employer letter, expert opinion, etc.)
    uploaded under the `supporting_docs` field name, each parsed into
    candidate PetitionArguments and merged with the structured petition
    JSON. See arguments_from_free_text's docstring for why this is
    paragraph-level keyword matching rather than semantic retrieval."""
    files = request.files.getlist("supporting_docs")
    allowed = ALLOWED_EXTENSIONS["supporting_docs"]
    args: list[PetitionArgument] = []
    for f in files:
        if not f or not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in allowed:
            raise ValueError(f"'supporting_docs' must be one of {sorted(allowed)}, got '{ext or f.filename}'")
        try:
            text = f.read().decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(f"supporting document '{f.filename}' is not a valid UTF-8 text file") from e
        args.extend(arguments_from_free_text(f.filename, text))
    return args


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", superdocs_key_set=bool(os.environ.get("SUPERDOCS_API_KEY")))


@app.route("/generate", methods=["POST"])
@_rate_limit(os.environ.get("GENERATE_RATE_LIMIT", "10 per hour"))
def generate():
    try:
        notice_text = _read_upload("notice")
        petition_text = _read_upload("petition")
        evidence_text = _read_upload("evidence")  # optional
        supporting_args = _read_supporting_docs()  # optional, multi-document
        case_id = request.form.get("case_id", "").strip()
        client_name = request.form.get("client_name", "").strip()
        dry_run = request.form.get("dry_run") == "on"

        if not notice_text:
            flash("Please upload an RFE notice (.txt).")
            return redirect(url_for("index"))
        if not petition_text:
            flash("Please upload a prior petition arguments file (.json).")
            return redirect(url_for("index"))
        if not case_id or not client_name:
            flash("Case ID and client name are required.")
            return redirect(url_for("index"))

        sanitize_case_id(case_id)  # raises ValueError on unusable input; used again downstream
        petition = _load_petition_from_text(petition_text)
        petition.arguments.extend(supporting_args)
        evidence_catalog = _load_evidence_catalog_from_text(evidence_text)

        if dry_run:
            requests_list, petition_matches, evidence_matches, exhibits, fuzzy_suggestions = plan_response(
                notice_text, petition, evidence_catalog
            )
            from rfe_response_builder.rfe import build_response_instruction, new_evidence_note_from_entries

            items = []
            for r in requests_list:
                prior = petition_matches[r.request_id]
                prior_arg = prior[0] if prior else None
                note = new_evidence_note_from_entries(evidence_matches[r.request_id])
                instruction = build_response_instruction(r, prior_arg, note)
                items.append(
                    {
                        "request_id": r.request_id,
                        "instruction": instruction,
                        "extra_prior_matches": [p.source_ref for p in prior[1:]] if len(prior) > 1 else [],
                        "fuzzy_suggestions": [
                            {"source_ref": arg.source_ref, "confidence": conf}
                            for arg, conf in fuzzy_suggestions.get(r.request_id, [])
                        ],
                    }
                )
            return render_template("results_dry_run.html", items=items, exhibits=exhibits, case_id=case_id)

        api_key = os.environ.get("SUPERDOCS_API_KEY")
        if not api_key:
            flash("SUPERDOCS_API_KEY is not configured on this server -- only dry run is available.")
            return redirect(url_for("index"))

        # Real runs always go through the human-review gate below rather
        # than drafting-and-exporting in one shot: SuperDocs holds each
        # section pending until reviewed, nothing reaches the exported
        # document without an explicit yes.
        client = SuperDocsClient(api_key=api_key)
        session_id = f"rfe-response-{sanitize_case_id(case_id)}-{uuid.uuid4().hex[:8]}"
        session = start_review(client, session_id, case_id, client_name, notice_text, petition,
                                evidence_catalog=evidence_catalog)
        review_id = _store_review_session(session)
        return redirect(url_for("review", review_id=review_id))

    except (ValueError, KeyError, json.JSONDecodeError) as e:
        flash(f"Could not process input: {e}")
        return redirect(url_for("index"))
    except SuperDocsError as e:
        logger.error("SuperDocs API error: %s", e)
        flash(f"SuperDocs API error: {e}")
        return redirect(url_for("index"))


@app.route("/review/<review_id>", methods=["GET"])
def review(review_id):
    session = _get_review_session(review_id)
    if session is None:
        flash("That review session was not found or has expired. Please start a new run.")
        return redirect(url_for("index"))
    return render_template("review.html", review_id=review_id, session=session)


@app.route("/review/<review_id>/approve", methods=["POST"])
@_rate_limit(os.environ.get("GENERATE_RATE_LIMIT", "10 per hour"))
def approve_review(review_id):
    session = _get_review_session(review_id)
    if session is None:
        flash("That review session was not found or has expired. Please start a new run.")
        return redirect(url_for("index"))

    decisions: dict[str, dict] = {}
    for item in session.items:
        approve = request.form.get(f"approve_{item.request_id}") == "on"
        feedback = request.form.get(f"feedback_{item.request_id}", "").strip() or None
        decisions[item.request_id] = {"approve": approve, "feedback": feedback}

    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key:
        flash("SUPERDOCS_API_KEY is not configured on this server -- cannot finalize a review.")
        return redirect(url_for("index"))

    client = SuperDocsClient(api_key=api_key)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            out_path, coverage = finalize_review(client, session, decisions, out_dir)
            unanswered = [row for row in coverage if not row.answered]
            if unanswered:
                logger.warning("case %s: %d/%d RFE item(s) NOT answered", session.safe_case_id, len(unanswered), len(coverage))
                flash(f"Generated, but {len(unanswered)} RFE item(s) were NOT answered -- see the coverage checklist in the doc.")
            else:
                logger.info("case %s: generated response, all %d item(s) answered", session.safe_case_id, len(coverage))
            _delete_review_session(review_id)
            return send_file(out_path, as_attachment=True, download_name=out_path.name)
    except SuperDocsError as e:
        logger.error("SuperDocs API error while finalizing review: %s", e)
        flash(f"SuperDocs API error: {e}")
        return redirect(url_for("review", review_id=review_id))


@app.route("/healthz")
def healthz():
    return {"status": "ok"}


@app.errorhandler(400)
def _bad_request(e):
    return render_template("error.html", title="Bad request", message=str(getattr(e, "description", e))), 400


@app.errorhandler(413)
def _payload_too_large(e):
    return render_template(
        "error.html", title="File too large",
        message=f"Uploaded files must be under {MAX_UPLOAD_MB} MB combined.",
    ), 413


@app.errorhandler(429)
def _rate_limited(e):
    return render_template(
        "error.html", title="Too many requests",
        message="You've hit the rate limit for generating responses. Please wait and try again.",
    ), 429


@app.errorhandler(500)
def _server_error(e):
    logger.exception("Unhandled server error")
    return render_template(
        "error.html", title="Something went wrong",
        message="An unexpected error occurred. Please try again; if it persists, contact support.",
    ), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # debug is intentionally never enabled from an env var here -- the
    # Werkzeug debugger exposes arbitrary code execution and must never be
    # reachable outside a developer's own machine running this by hand.
    app.run(host="0.0.0.0", port=port)
