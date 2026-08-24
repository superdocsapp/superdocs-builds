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

from flask import Flask, flash, g, redirect, render_template, request, send_file, url_for
from flask import session as flask_session
from jobs import JobRunner, JobStore, STATUS_COMPLETED, STATUS_FAILED
from review_store import ReviewSessionStore
from werkzeug.middleware.proxy_fix import ProxyFix

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rfe_response_builder.audit import log_decision
from rfe_response_builder.document_extraction import DocumentExtractionError, extract_text
from rfe_response_builder.firm_templates import (
    FirmTemplate,
    FirmTemplateValidationError,
    apply_firm_customization,
)
from rfe_response_builder.generate import plan_response
from rfe_response_builder.grounding import check_grounding
from rfe_response_builder.logging_config import configure_logging, set_case_id, set_request_id
from rfe_response_builder.review import finalize_review, start_review
from rfe_response_builder.rfe import (
    NewEvidenceCatalog,
    NewEvidenceEntry,
    PetitionArgument,
    PriorPetition,
    arguments_from_free_text,
    sanitize_case_id,
)
from rfe_response_builder.schemas import SchemaValidationError, validate_evidence_json, validate_petition_json
from rfe_response_builder.superdocs_client import SuperDocsClient, SuperDocsError
from rfe_response_builder.versioning import VersionStore, diff_versions, redraft_item

configure_logging()
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
    "firm_template": {".json"},
    "supporting_docs": {".txt", ".pdf", ".docx"},
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


# --- Background job queue ------------------------------------------------------
# Real (non-dry-run) generation now runs in a background thread instead of
# inside the request -- see jobs.py's module docstring for why. Reuses
# _review_store's engine/database so there's one store to provision, not
# two, while keeping the job data in its own table.
_job_store = JobStore(_review_store.engine)
_job_runner = JobRunner(_job_store, max_workers=int(os.environ.get("JOB_WORKERS", "2")))

# --- Draft version history (see versioning.py) ---------------------------------
# Same engine-sharing pattern as _job_store -- one database to provision.
_version_store = VersionStore(_review_store.engine)


# --- Ownership (lightweight, session-cookie-scoped access control) ------------
# This is NOT full multi-tenant auth -- there is still no login/user
# accounts. What it does fix: review_id and job_id are opaque uuid4 hex
# strings, but the original build had NO check at all beyond that --
# anyone who guessed or was handed a URL could view or approve someone
# else's pending review. This ties ownership to the browser's signed
# session cookie (Flask's default session, HMAC-signed with
# FLASK_SECRET_KEY -- not forgeable without the server's secret) so only
# the browser that started a given job/review can view or act on it.
# A real firm-account system would replace this with per-user/per-firm
# database-backed ACLs; this is the pragmatic fix for the "guessable URL"
# gap specifically.
def _own_job(job_id: str) -> None:
    owned = flask_session.get("owned_jobs", [])
    owned.append(job_id)
    flask_session["owned_jobs"] = owned


def _owns_job(job_id: str) -> bool:
    return job_id in flask_session.get("owned_jobs", [])


def _own_review(review_id: str) -> None:
    owned = flask_session.get("owned_reviews", [])
    owned.append(review_id)
    flask_session["owned_reviews"] = owned


def _owns_review(review_id: str) -> bool:
    if review_id in flask_session.get("owned_reviews", []):
        return True
    # Fallback: a review reached via its originating job_id counts as
    # owned even if the browser never hit the /jobs/<id> status page
    # long enough to have review ownership recorded there (e.g. it
    # completed between the redirect and the first status poll).
    for job_id in flask_session.get("owned_jobs", []):
        job = _job_store.get(job_id)
        if job and job.review_id == review_id:
            return True
    return False

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


@app.before_request
def _assign_request_id():
    g.request_id = uuid.uuid4().hex[:12]
    set_request_id(g.request_id)
    set_case_id(request.form.get("case_id") if request.method == "POST" else None)


@app.after_request
def _add_request_id_header(response):
    if getattr(g, "request_id", None):
        response.headers["X-Request-ID"] = g.request_id
    return response


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
    validate_petition_json(raw)
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
    validate_evidence_json(raw)
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
    """Multi-document ingestion: any number of supporting documents
    (petition letter, employer letter, expert opinion, etc.) uploaded
    under the `supporting_docs` field name -- accepts .txt/.pdf/.docx
    (see document_extraction.py for the actual extraction), each parsed
    into candidate PetitionArguments and merged with the structured
    petition JSON. See arguments_from_free_text's docstring for why this
    is paragraph-level keyword matching rather than semantic retrieval.

    PDF/DOCX extraction libraries need a real file path, not an in-memory
    stream, so each upload is written to a temp file first (cleaned up
    immediately after extraction, success or failure) rather than kept
    only in memory the way the plain-text uploads elsewhere in this
    route are."""
    files = request.files.getlist("supporting_docs")
    allowed = ALLOWED_EXTENSIONS["supporting_docs"]
    args: list[PetitionArgument] = []
    for f in files:
        if not f or not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in allowed:
            raise ValueError(f"'supporting_docs' must be one of {sorted(allowed)}, got '{ext or f.filename}'")
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(f.read())
            tmp_path = Path(tmp.name)
        try:
            text = extract_text(tmp_path)
        except DocumentExtractionError as e:
            raise ValueError(str(e)) from e
        finally:
            tmp_path.unlink(missing_ok=True)
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
        firm_template_text = _read_upload("firm_template")  # optional
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
        firm_template = FirmTemplate.from_dict(json.loads(firm_template_text)) if firm_template_text else None

        if dry_run:
            requests_list, petition_matches, evidence_matches, exhibits, fuzzy_suggestions = plan_response(
                notice_text, petition, evidence_catalog
            )
            from rfe_response_builder.classify import RFECategory, classify, extract_response_deadline
            from rfe_response_builder.injection_guard import scan_all_inputs_for_injection_risk
            from rfe_response_builder.rfe import build_response_instruction, new_evidence_note_from_entries

            classification = classify(notice_text)
            profile = classification.profile
            deadline = extract_response_deadline(notice_text)
            injection_flags = scan_all_inputs_for_injection_risk(
                notice_text=notice_text, petition=petition, evidence_catalog=evidence_catalog,
                firm_template=firm_template,
            )
            framework_note = (
                profile.legal_framework_note if classification.category != RFECategory.UNKNOWN else None
            )

            items = []
            for r in requests_list:
                prior = petition_matches[r.request_id]
                prior_arg = prior[0] if prior else None
                note = new_evidence_note_from_entries(evidence_matches[r.request_id])
                instruction = build_response_instruction(r, prior_arg, note, legal_framework_note=framework_note)
                instruction = apply_firm_customization(instruction, firm_template, classification.category.value)
                tier, suggestion_matches = fuzzy_suggestions.get(r.request_id, ("none", []))
                items.append(
                    {
                        "request_id": r.request_id,
                        "instruction": instruction,
                        "extra_prior_matches": [p.source_ref for p in prior[1:]] if len(prior) > 1 else [],
                        "fuzzy_suggestions": [
                            {"source_ref": arg.source_ref, "confidence": conf, "tier": tier}
                            for arg, conf in suggestion_matches
                        ],
                    }
                )
            return render_template(
                "results_dry_run.html", items=items, exhibits=exhibits, case_id=case_id,
                classification=classification, profile=profile, deadline=deadline, firm_template=firm_template,
                injection_flags=injection_flags,
            )

        api_key = os.environ.get("SUPERDOCS_API_KEY")
        if not api_key:
            flash("SUPERDOCS_API_KEY is not configured on this server -- only dry run is available.")
            return redirect(url_for("index"))

        # Real runs always go through the human-review gate below rather
        # than drafting-and-exporting in one shot: SuperDocs holds each
        # section pending until reviewed, nothing reaches the exported
        # document without an explicit yes. This work now happens in a
        # background job (see jobs.py) instead of inside this request --
        # a real filing can take a minute or more (one turn per RFE item),
        # which would otherwise tie up a gunicorn worker for that whole
        # duration.
        job_id = _job_store.create(case_id=case_id)
        _own_job(job_id)

        def _do_review_run(_case_id=case_id, _client_name=client_name, _notice_text=notice_text,
                            _petition=petition, _evidence_catalog=evidence_catalog, _api_key=api_key,
                            _firm_template=firm_template, _job_id=job_id):
            client = SuperDocsClient(api_key=_api_key)
            session_id = f"rfe-response-{sanitize_case_id(_case_id)}-{uuid.uuid4().hex[:8]}"

            def _on_item_progress(completed: int, total: int, current_item_label: str) -> None:
                _job_store.update_progress(_job_id, completed=completed, total=total,
                                            current_item_label=current_item_label)

            review_session = start_review(client, session_id, _case_id, _client_name, _notice_text,
                                           _petition, evidence_catalog=_evidence_catalog,
                                           firm_template=_firm_template, progress_callback=_on_item_progress)
            review_id = _store_review_session(review_session)
            # Record version 1 for every item that actually has drafted
            # text -- this is what a later "redraft with feedback" diffs
            # against. See versioning.py.
            for item in review_session.items:
                if item.reply_text:
                    _version_store.record(review_id, item.request_id, item.reply_text)
            return review_id

        _job_runner.submit(job_id, _do_review_run)
        return redirect(url_for("job_status", job_id=job_id))

    except (ValueError, KeyError, json.JSONDecodeError) as e:
        flash(f"Could not process input: {e}")
        return redirect(url_for("index"))
    except SuperDocsError as e:
        logger.error("SuperDocs API error: %s", e)
        flash(f"SuperDocs API error: {e}")
        return redirect(url_for("index"))


@app.route("/jobs/<job_id>", methods=["GET"])
def job_status(job_id):
    if not _owns_job(job_id):
        flash("That job was not found or has expired, or does not belong to this browser session.")
        return redirect(url_for("index"))
    job = _job_store.get(job_id)
    if job is None:
        flash("That job was not found or has expired. Please start a new run.")
        return redirect(url_for("index"))
    if job.status == STATUS_COMPLETED:
        # Recorded here (inside a real request, with a request context)
        # rather than from the background thread, which has none -- see
        # _own_review's docstring note above.
        _own_review(job.review_id)
        return redirect(url_for("review", review_id=job.review_id))
    if job.status == STATUS_FAILED:
        flash(f"Drafting failed: {job.error}")
        return redirect(url_for("index"))
    return render_template(
        "job_status.html", job_id=job_id, status=job.status,
        items_completed=job.items_completed, items_total=job.items_total,
        current_item_label=job.current_item_label,
    )


@app.route("/jobs/<job_id>/status", methods=["GET"])
def job_status_json(job_id):
    """JSON polling endpoint for clients that prefer AJAX polling over
    the meta-refresh page above (e.g. a future JS-driven UI, or an API
    consumer). Same ownership check as the HTML page."""
    if not _owns_job(job_id):
        return {"error": "not found"}, 404
    job = _job_store.get(job_id)
    if job is None:
        return {"error": "not found"}, 404
    body = {
        "job_id": job.job_id, "status": job.status,
        "items_completed": job.items_completed, "items_total": job.items_total,
        "current_item_label": job.current_item_label,
    }
    if job.status == STATUS_COMPLETED:
        _own_review(job.review_id)
        body["review_url"] = url_for("review", review_id=job.review_id)
    elif job.status == STATUS_FAILED:
        body["error"] = job.error
    return body


@app.route("/review/<review_id>", methods=["GET"])
def review(review_id):
    if not _owns_review(review_id):
        flash("That review session was not found or has expired, or does not belong to this browser session.")
        return redirect(url_for("index"))
    session = _get_review_session(review_id)
    if session is None:
        flash("That review session was not found or has expired. Please start a new run.")
        return redirect(url_for("index"))
    # Version history + diff-against-previous for each item, for the
    # "show what changed" panel in review.html. Only items with more than
    # one recorded version have anything to show.
    version_info: dict[str, dict] = {}
    for item in session.items:
        versions = _version_store.list_versions(review_id, item.request_id)
        if len(versions) > 1:
            version_info[item.request_id] = {
                "count": len(versions),
                "diff": diff_versions(versions[-2].reply_text, versions[-1].reply_text),
            }
    return render_template("review.html", review_id=review_id, session=session, version_info=version_info)


@app.route("/review/<review_id>/redraft/<request_id>", methods=["POST"])
@_rate_limit(os.environ.get("GENERATE_RATE_LIMIT", "10 per hour"))
def redraft_review_item(review_id, request_id):
    if not _owns_review(review_id):
        flash("That review session was not found or has expired, or does not belong to this browser session.")
        return redirect(url_for("index"))
    session = _get_review_session(review_id)
    if session is None:
        flash("That review session was not found or has expired. Please start a new run.")
        return redirect(url_for("index"))
    item = next((i for i in session.items if i.request_id == request_id), None)
    if item is None:
        flash(f"No item {request_id} found in this review session.")
        return redirect(url_for("review", review_id=review_id))

    feedback = request.form.get("redraft_feedback", "").strip()
    if not feedback:
        flash("Enter feedback describing what should change before requesting a redraft.")
        return redirect(url_for("review", review_id=review_id))

    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key:
        flash("SUPERDOCS_API_KEY is not configured on this server -- cannot redraft.")
        return redirect(url_for("review", review_id=review_id))

    try:
        client = SuperDocsClient(api_key=api_key)
        reply_text, status, chunk_id = redraft_item(
            client, session.session_id, request_id, item.response_section, feedback,
        )
    except SuperDocsError as e:
        logger.error("redraft failed for review %s item %s: %s", review_id, request_id, e)
        flash(f"Redraft failed: {e}")
        return redirect(url_for("review", review_id=review_id))

    _version_store.record(review_id, request_id, reply_text, feedback=feedback)
    item.reply_text = reply_text
    item.status = status
    item.job_id = chunk_id
    # Re-run the fact-grounding check against the new text -- a redraft
    # can just as easily introduce an unsupported detail as an initial
    # draft can.
    source_texts = [item.request_text] + list(item.new_evidence)
    grounding_result = check_grounding(reply_text, source_texts)
    item.ungrounded_facts = grounding_result.ungrounded_facts
    _review_store.put(review_id, session)

    flash(f"Item {request_id} redrafted based on your feedback -- review the new version below.")
    return redirect(url_for("review", review_id=review_id))


@app.route("/review/<review_id>/approve", methods=["POST"])
@_rate_limit(os.environ.get("GENERATE_RATE_LIMIT", "10 per hour"))
def approve_review(review_id):
    if not _owns_review(review_id):
        flash("That review session was not found or has expired, or does not belong to this browser session.")
        return redirect(url_for("index"))
    session = _get_review_session(review_id)
    if session is None:
        flash("That review session was not found or has expired. Please start a new run.")
        return redirect(url_for("index"))

    decisions: dict[str, dict] = {}
    reviewer = (request.form.get("reviewer_name", "").strip() or request.headers.get("X-Reviewer-Id", "").strip()
                or "unknown")
    for item in session.items:
        approve = request.form.get(f"approve_{item.request_id}") == "on"
        feedback = request.form.get(f"feedback_{item.request_id}", "").strip() or None
        decisions[item.request_id] = {"approve": approve, "feedback": feedback}
        # Audited at decision time (not only on successful export) so the
        # record of what a human decided survives even if the SuperDocs
        # export step below fails partway through -- the decision itself
        # already happened and is worth keeping regardless of export outcome.
        log_decision(
            case_id=session.safe_case_id, request_id=item.request_id,
            action="approve" if approve else "reject", reviewer=reviewer,
            feedback=feedback, response_section=(item.response_section or "")[:2000],
        )

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
    """Liveness: is the process up and able to handle a request at all.
    Deliberately does NOT touch the review-session store or any external
    dependency -- that's what /readyz is for. Render's healthCheckPath
    stays pointed at this one so a slow/unavailable database doesn't
    cause Render to kill and restart an otherwise-healthy instance."""
    return {"status": "ok"}


@app.route("/readyz")
def readyz():
    """Readiness: is this instance able to actually serve real (non-dry-run)
    traffic right now -- i.e. can it reach the review-session store.
    Returns 503 (not 200) if the store is unreachable, so a load balancer
    or orchestrator can route traffic away from this instance instead of
    sending it requests that will fail once they hit /generate or
    /review/<id>."""
    checks: dict[str, str] = {}
    ok = True
    try:
        with _review_store.engine.connect():
            pass
        checks["review_store"] = f"ok ({_review_store.backend})"
    except Exception as e:  # pragma: no cover - exercised only when the store is actually down
        ok = False
        checks["review_store"] = f"error: {e}"
    checks["superdocs_api_key_configured"] = "yes" if os.environ.get("SUPERDOCS_API_KEY") else "no (dry-run only)"
    return checks, 200 if ok else 503


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
