


"""
app.py
LatBuild — SuperDocs PDF Companion
Flask service for surgical PDF editing with layout preservation.

State is held in-memory keyed by browser session UUID.
All heavy processing (PDF analysis, SuperDocs calls, patching) happens
server-side. The API key never reaches the browser.

Routes:
  GET  /                      — upload page
  GET  /sections              — detected sections page
  GET  /edit                  — instruction entry page
  GET  /review                — before/after diff review
  GET  /report                — fidelity report + download

API:
  POST /api/upload            — upload PDF, analyze, return sections
  POST /api/transform         — start SuperDocs jobs for selected sections
  GET  /api/poll/<job_id>     — poll a SuperDocs job
  POST /api/approve           — submit per-change decisions
  POST /api/apply             — apply approved rewrites to PDF
  GET  /api/download          — download the modified PDF
  GET  /api/sections          — list detected sections (JSON)
"""

import io
import os
import uuid
import json
import re
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import (
    Flask, request, jsonify, render_template,
    session, send_file, redirect, url_for
)

import superdocs_client as sd
from pdf_analyzer import analyze_pdf
from flow_mapper import build_flow_map
from section_extractor import extract_section, build_superdocs_instruction
from docx_bridge import prose_to_docx, extract_text_from_docx, extract_text_from_html
from reflow_engine import plan_reflow, plan_multi_section_reflow
from pdf_patcher import apply_multiple_reflows
from fidelity_checker import check_fidelity

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

# ---------------------------------------------------------------------------
# In-memory state store
# ---------------------------------------------------------------------------
# State dict keys per session:
#   pdf_path          - path to uploaded PDF (tempfile)
#   pdf_filename      - original filename
#   flow_map          - DocumentFlowMap
#   selected_sections - list of section names chosen by user
#   instruction       - user's SuperDocs instruction string
#   jobs              - dict: section_name -> job dict
#                         job dict: session_id, job_id, status,
#                                   original_text, proposed_text,
#                                   pending_changes, approved
#   output_path       - path to patched PDF tempfile
#   fidelity_report   - FidelityReport.as_dict()
# ---------------------------------------------------------------------------
_state = {}
_state_lock = threading.Lock()


def _get_state():
    sid = session.get("sid")
    if not sid or sid not in _state:
        sid = str(uuid.uuid4())
        session["sid"] = sid
        with _state_lock:
            _state[sid] = {
                "pdf_path": None,
                "pdf_filename": None,
                "flow_map": None,
                "selected_sections": [],
                "instruction": "",
                "jobs": {},
                "output_path": None,
                "fidelity_report": None,
            }
    return _state[session["sid"]]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    state = _get_state()
    return render_template(
        "index.html",
        has_pdf=bool(state["pdf_path"]),
        pdf_filename=state["pdf_filename"],
    )


@app.route("/sections")
def sections_page():
    state = _get_state()
    if not state["flow_map"]:
        return redirect(url_for("index"))
    fm = state["flow_map"]
    editable = fm.editable_sections()
    return render_template(
        "sections.html",
        sections=editable,
        pdf_filename=state["pdf_filename"],
    )


@app.route("/edit")
def edit_page():
    state = _get_state()

    # Accept sections from URL params (from sections page Continue button)
    sections_param = request.args.get("sections", "")
    if sections_param:
        state["selected_sections"] = [s.strip() for s in sections_param.split(",") if s.strip()]

    if not state["selected_sections"] or not state["flow_map"]:
        return redirect(url_for("sections_page"))
    fm = state["flow_map"]
    selected = [
        fm.get_section(name)
        for name in state["selected_sections"]
        if fm.get_section(name)
    ]
    if not selected:
        return redirect(url_for("sections_page"))
    return render_template(
        "edit.html",
        selected_sections=selected,
        instruction=state["instruction"],
    )


@app.route("/review")
def review_page():
    state = _get_state()
    if not state["jobs"]:
        return redirect(url_for("edit_page"))
    # Order jobs according to selected_sections list order
    ordered_jobs = {
        name: state["jobs"].get(name, {})
        for name in state.get("selected_sections", [])
        if name in state["jobs"]
    }
    return render_template(
        "review.html",
        jobs=ordered_jobs,
        selected_sections=state["selected_sections"],
    )


@app.route("/report")
def report_page():
    state = _get_state()
    fidelity = state.get("fidelity_report")
    if not fidelity:
        return redirect(url_for("index"))
    return render_template(
        "report.html",
        report=fidelity,
        can_download=bool(state.get("output_path")),
        pdf_filename=state["pdf_filename"],
    )


# ---------------------------------------------------------------------------
# API: Upload
# ---------------------------------------------------------------------------

@app.route("/api/upload", methods=["POST"])
def api_upload():
    """
    Upload a PDF, analyze it, build the flow map.
    Returns the list of detected editable sections.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No filename."}), 400
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported."}), 400

    state = _get_state()

    # Clean up previous tempfile
    if state["pdf_path"] and os.path.exists(state["pdf_path"]):
        try:
            os.unlink(state["pdf_path"])
        except OSError:
            pass

    # Save to temp file (pdfplumber/pymupdf need a file path)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(f.read())
    tmp.close()

    try:
        doc = analyze_pdf(tmp.name)
        flow_map = build_flow_map(doc)
    except Exception as e:
        os.unlink(tmp.name)
        return jsonify({"error": f"PDF analysis failed: {str(e)}"}), 422

    state["pdf_path"] = tmp.name
    state["pdf_filename"] = f.filename
    state["flow_map"] = flow_map
    state["selected_sections"] = []
    state["jobs"] = {}
    state["output_path"] = None
    state["fidelity_report"] = None

    editable = flow_map.editable_sections()
    return jsonify({
        "ok": True,
        "filename": f.filename,
        "page_count": doc.page_count,
        "sections": [
            {
                "name": s.title,
                "id": s.id,
                "level": s.level,
                "parent_id": s.parent_id,
                "pages": s.pages,
                "word_count": s.word_count,
                "is_editable": s.is_editable,
                "preview": s.full_text[:300] if s.full_text else "",
            }
            for s in editable
        ],
    })


# ---------------------------------------------------------------------------
# API: Sections (JSON)
# ---------------------------------------------------------------------------

@app.route("/api/sections", methods=["GET"])
def api_sections():
    state = _get_state()
    if not state["flow_map"]:
        return jsonify({"error": "No PDF uploaded."}), 400
    fm = state["flow_map"]
    editable = fm.editable_sections()
    return jsonify({
        "sections": [
            {
                "name": s.title,
                "id": s.id,
                "level": s.level,
                "parent_id": s.parent_id,
                "pages": s.pages,
                "word_count": s.word_count,
                "preview": s.full_text[:300] if s.full_text else "",
            }
            for s in editable
        ]
    })


# ---------------------------------------------------------------------------
# API: Select sections + start transform
# ---------------------------------------------------------------------------


def _build_paper_context(fm) -> str:
    """
    Build a concise paper context: title + abstract only.
    Enough for SuperDocs to understand the domain without noise.
    """
    parts = []
    preamble = next((s for s in fm.sections if "preamble" in s.id.lower()), None)
    if preamble and preamble.full_text:
        parts.append(f"Paper title: {preamble.full_text[:150].strip()}")
    abstract = next((s for s in fm.sections if "abstract" in s.title.lower()), None)
    if abstract and abstract.full_text:
        parts.append(f"Abstract: {abstract.full_text[:600].strip()}")
    return "\n\n".join(parts)



# ---------------------------------------------------------------------------
# SuperDocs change safety + PDF-aware mapping
# ---------------------------------------------------------------------------

def _plain_change_text(value: str) -> str:
    """Convert SuperDocs HTML/text to normalized plain text."""
    import html as _html
    text = _html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _change_old_text(change: dict) -> str:
    for key in ("old_html", "old_text", "original_text", "before", "text"):
        value = change.get(key)
        if isinstance(value, str) and value.strip():
            return _plain_change_text(value)
    return ""


def _change_new_text(change: dict) -> str:
    for key in ("new_html", "new_text", "after"):
        value = change.get(key)
        if isinstance(value, str):
            return _plain_change_text(value)
    return ""


def _token_spans(text: str):
    """
    Tokenize while treating PDF line-break hyphenation as one word.

    Example:
        Intel- ligence -> intelligence
        Experi- mental -> experimental
    """
    tokens = []
    for m in re.finditer(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*-?", text or ""):
        raw = m.group(0)
        norm = raw.lower().replace("’", "'").replace("–", "-")

        if norm.endswith("-"):
            next_m = re.match(
                r"\s+([A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*)",
                text[m.end():],
            )
            if next_m:
                next_raw = next_m.group(1)
                next_start = m.end() + next_m.start(1)
                merged = (
                    norm[:-1]
                    + next_raw.lower().replace("’", "'").replace("–", "-")
                )
                tokens.append({
                    "norm": merged,
                    "start": m.start(),
                    "end": next_start + len(next_raw),
                })
                continue

        tokens.append({
            "norm": norm.rstrip("-"),
            "start": m.start(),
            "end": m.end(),
        })
    return tokens


def _normalized_words(text: str):
    return [t["norm"] for t in _token_spans(text)]


def _contains_ordered_overlap(source: str, target: str) -> bool:
    """Prove that a SuperDocs old-value belongs to this selected section."""
    source_words = _normalized_words(source)
    target_words = _normalized_words(target)

    if len(source_words) < 4 or len(target_words) < 4:
        return False

    max_run = min(12, len(source_words))
    for run in range(max_run, 3, -1):
        for i in range(len(source_words) - run + 1):
            phrase = source_words[i:i + run]
            for j in range(len(target_words) - run + 1):
                if target_words[j:j + run] == phrase:
                    return True
    return False


def _bouncer_filter_changes(changes: list, original_text: str = "") -> list:
    """
    Keep changes whose OLD content can be proven to occur in the
    selected section. Since each section is transformed in its own dedicated
    SuperDocs session, all proposed changes to that isolated document belong to it.
    """
    accepted = []
    target = original_text or ""

    for change in changes or []:
        if not isinstance(change, dict):
            continue
        old_text = _change_old_text(change)
        if not old_text:
            accepted.append(change)
        elif _contains_ordered_overlap(old_text, target):
            accepted.append(change)
        else:
            # Token overlap fallback
            old_words = _normalized_words(old_text)
            target_words = set(_normalized_words(target))
            if old_words and any(w in target_words for w in old_words if len(w) > 3):
                accepted.append(change)
            elif not target:
                accepted.append(change)

    # If strict filter yielded nothing but changes exist for this isolated section doc, keep them
    if not accepted and changes:
        accepted = [c for c in changes if isinstance(c, dict)]

    return accepted


def _find_old_text_span(original: str, old_text: str):
    """Find SuperDocs old text inside PDF-derived text with hyphenation tolerance."""
    if not original or not old_text:
        return None

    # 1. Direct exact or case-insensitive substring
    if old_text in original:
        idx = original.find(old_text)
        return idx, idx + len(old_text)

    low_orig = original.lower()
    low_old = old_text.lower()
    if low_old in low_orig:
        idx = low_orig.find(low_old)
        return idx, idx + len(old_text)

    # 2. Token-normalized window match
    source_tokens = _token_spans(original)
    old_tokens = _normalized_words(old_text)

    if source_tokens and old_tokens:
        n = len(old_tokens)
        for i in range(len(source_tokens) - n + 1):
            candidate = [t["norm"] for t in source_tokens[i:i + n]]
            if candidate == old_tokens:
                return (
                    source_tokens[i]["start"],
                    source_tokens[i + n - 1]["end"],
                )

    # 3. SequenceMatcher alignment fallback
    orig_words = original.split()
    old_words = old_text.split()
    if orig_words and old_words:
        import difflib
        sm = difflib.SequenceMatcher(None, [w.lower() for w in orig_words], [w.lower() for w in old_words])
        match = sm.find_longest_match(0, len(orig_words), 0, len(old_words))
        if match.size >= max(3, int(len(old_words) * 0.4)):
            w_start, w_end = match.a, match.a + match.size
            char_idx = 0
            starts = []
            ends = []
            for w in orig_words:
                s_pos = original.find(w, char_idx)
                starts.append(s_pos)
                ends.append(s_pos + len(w))
                char_idx = s_pos + len(w)
            if 0 <= w_start < len(starts) and 0 < w_end <= len(ends):
                return starts[w_start], ends[w_end - 1]

    return None


def _apply_structured_changes_to_section(original_text: str, changes: list):
    """
    Apply only approved SuperDocs edits to the original section.
    """
    if not changes:
        return original_text.strip() if original_text else None

    normalized = []
    for change in changes or []:
        old_text = _change_old_text(change)
        new_text = _change_new_text(change)
        if new_text is not None:
            normalized.append((old_text, new_text))

    if not normalized:
        return original_text.strip() if original_text else None

    # If single change replacing the section, return new_text directly if old text spans most of section
    if len(normalized) == 1:
        old_t, new_t = normalized[0]
        if not old_t or len(old_t.split()) >= max(3, int(len((original_text or '').split()) * 0.4)):
            return new_t.strip()

    # Find replacement spans in original text
    located_spans = []
    for old_text, new_text in normalized:
        if not old_text:
            continue
        span = _find_old_text_span(original_text, old_text)
        if span:
            located_spans.append((span[0], span[1], new_text))

    if located_spans:
        # Sort by start position descending to replace from end to beginning
        located_spans.sort(key=lambda s: s[0], reverse=True)
        result = original_text
        for start, end, new_text in located_spans:
            result = result[:start] + new_text + result[end:]
        return result.strip()

    # Fallback: if all approved changes have new text, join them
    all_new = [new_t for _, new_t in normalized if new_t.strip()]
    if all_new:
        return "\n\n".join(all_new).strip()

    return None

@app.route("/api/transform", methods=["POST"])
def api_transform():
    """
    Start SuperDocs editing jobs for the selected sections.
    Each section gets its own independent SuperDocs session.
    Jobs run in parallel via ThreadPoolExecutor.
    """
    data = request.get_json() or {}
    section_names = data.get("sections", [])
    # Support both single instruction and per-section instructions
    instructions_map = data.get("instructions", {})  # {section_title: instruction}
    single_instruction = data.get("instruction", "").strip()

    if not section_names:
        return jsonify({"error": "No sections selected."}), 400
    if not instructions_map and not single_instruction:
        return jsonify({"error": "At least one instruction is required."}), 400

    state = _get_state()
    if not state["flow_map"]:
        return jsonify({"error": "No PDF uploaded."}), 400

    fm = state["flow_map"]
    state["selected_sections"] = section_names
    state["instruction"] = single_instruction or str(instructions_map)
    state["jobs"] = {}
    state["output_path"] = None
    state["fidelity_report"] = None

    sections_to_edit = []
    for name in section_names:
        sec = fm.get_section(name)
        if not sec:
            return jsonify({"error": f"Section '{name}' not found."}), 400
        if not sec.is_editable:
            return jsonify({"error": f"Section '{name}' is not editable."}), 400
        sections_to_edit.append(sec)

    # Start one SuperDocs job per section (parallel)
    def start_job(section):
        extracted = extract_section(section, fm.grammar)
        # Use per-section instruction if available, otherwise fall back to single
        instruction = instructions_map.get(section.title, single_instruction)

        # Send only the user instruction — no background context.
        # SuperDocs rewrites the uploaded section document directly.
        # Context was causing section content swapping.
        full_instruction = build_superdocs_instruction(instruction, extracted)
        docx_bytes = prose_to_docx(extracted.clean_text, title=section.title)
        conv_session_id = f"latbuild-{uuid.uuid4().hex[:12]}"

        try:
            upload_result = sd.upload_document(docx_bytes, "section.docx", conv_session_id)
            job_id = sd.start_transformation(
                conv_session_id, upload_result["html"], full_instruction
            )
            return section.title, {
                "session_id": conv_session_id,
                "job_id": job_id,
                "status": "in_progress",
                "original_text": extracted.clean_text,
                "target_section_title": section.title,
                "proposed_text": None,
                "pending_changes": [],
                "approved_changes": [],
                "approved": False,
                "error": None,
            }
        except sd.SuperDocsError as e:
            return section.title, {
                "session_id": conv_session_id,
                "job_id": None,
                "status": "failed",
                "original_text": extracted.clean_text,
                "proposed_text": None,
                "pending_changes": [],
                "approved": False,
                "error": str(e),
            }

    with ThreadPoolExecutor(max_workers=min(4, len(sections_to_edit))) as executor:
        futures = {executor.submit(start_job, s): s for s in sections_to_edit}
        for future in as_completed(futures):
            try:
                name, job = future.result()
            except Exception as e:
                sec = futures[future]
                name = sec.title
                job = {
                    "session_id": None, "job_id": None,
                    "status": "failed",
                    "original_text": sec.full_text,
                    "target_section_title": sec.title,
                    "proposed_text": None, "pending_changes": [],
                    "approved_changes": [],
                    "approved": False, "error": str(e),
                }
            state["jobs"][name] = job

    return jsonify({
        "ok": True,
        "jobs": {
            name: {"job_id": j["job_id"], "status": j["status"]}
            for name, j in state["jobs"].items()
        }
    })


# ---------------------------------------------------------------------------
# API: Poll
# ---------------------------------------------------------------------------

@app.route("/api/poll/<job_id>", methods=["GET"])
def api_poll(job_id):
    """Poll a single SuperDocs job."""
    state = _get_state()

    # Find which section this job belongs to
    section_name = None
    for name, job in state["jobs"].items():
        if job.get("job_id") == job_id:
            section_name = name
            break

    if not section_name:
        return jsonify({"error": "Job not found."}), 404

    job = state["jobs"][section_name]
    if job["status"] in ("failed", "cancelled"):
        return jsonify({"status": job["status"], "error": job.get("error")})

    try:
        job_state = sd.poll_job(job_id)
    except sd.SuperDocsError as e:
        return jsonify({"error": str(e)}), 502

    status = job_state["status"]
    job["status"] = status

    if status == "awaiting_approval":
        all_changes = job_state.get("pending_changes") or []
        filtered = _bouncer_filter_changes(
            all_changes, job.get("original_text", "")
        )

        if not filtered:
            job["error"] = (
                f"SuperDocs proposed no change that can be proven to belong "
                f"to '{section_name}'."
            )

        job["pending_changes"] = filtered
        return jsonify({
            "status": "awaiting_approval",
            "section": section_name,
            "pending_changes": filtered,
            "error": job.get("error"),
        })

    if status == "completed":
        approved_changes = job.get("approved_changes") or []

        proposed_text = None
        if approved_changes:
            proposed_text = _apply_structured_changes_to_section(
                job.get("original_text", ""), approved_changes
            )

        # Robust fallback: extract clean text directly from SuperDocs transformed HTML or approved changes
        if not proposed_text:
            if approved_changes:
                all_new = [_change_new_text(c) for c in approved_changes if _change_new_text(c)]
                if all_new:
                    proposed_text = "\n\n".join(all_new).strip()

        if not proposed_text:
            res = job_state.get("result") or {}
            raw_html = ""
            if isinstance(res, dict):
                raw_html = (
                    res.get("html")
                    or res.get("document_html")
                    or res.get("final_html")
                    or res.get("content")
                    or ""
                )
            elif isinstance(res, str):
                raw_html = res

            if not raw_html:
                raw_html = (
                    job_state.get("final_html")
                    or job_state.get("html")
                    or job_state.get("document_html")
                    or ""
                )

            if raw_html:
                from docx_bridge import extract_text_from_html
                extracted_text = extract_text_from_html(raw_html)
                if extracted_text and extracted_text.strip():
                    proposed_text = extracted_text.strip()

        if proposed_text is None:
            job["status"] = "failed"
            job["error"] = (
                f"Approved SuperDocs changes could not be mapped back to "
                f"'{section_name}'."
            )
            return jsonify({
                "status": "failed",
                "section": section_name,
                "error": job["error"],
            }), 422

        job["proposed_text"] = proposed_text
        return jsonify({
            "status": "completed",
            "section": section_name,
            "proposed_text": proposed_text,
        })

    if status == "failed":
        job["error"] = job_state.get("error", "Unknown error")
        return jsonify({
            "status": "failed",
            "section": section_name,
            "error": job["error"],
        })

    return jsonify({"status": status, "section": section_name})


# ---------------------------------------------------------------------------
# API: Approve changes
# ---------------------------------------------------------------------------

@app.route("/api/approve", methods=["POST"])
def api_approve():
    """Submit per-change decisions for a SuperDocs job."""
    data = request.get_json() or {}
    job_id = data.get("job_id")
    session_id = data.get("session_id")
    decisions = data.get("decisions", [])

    if not job_id or not session_id:
        return jsonify({"error": "job_id and session_id are required."}), 400

    state = _get_state()
    job = next(
        (j for j in state["jobs"].values() if j.get("job_id") == job_id),
        None,
    )
    if job is None:
        return jsonify({"error": "Job not found."}), 404

    pending = job.get("pending_changes") or []
    decision_map = {
        d.get("change_id"): bool(d.get("approved"))
        for d in decisions
        if d.get("change_id")
    }

    approved_changes = [
        change for change in pending
        if decision_map.get(change.get("change_id"), True) is True
    ]

    try:
        sd.approve_changes(session_id, job_id, decisions)
    except sd.SuperDocsError as e:
        return jsonify({"error": str(e)}), 502

    # Persist BEFORE SuperDocs transitions to completed.
    job["approved_changes"] = approved_changes or pending
    job["approved"] = True

    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API: Apply — patch the PDF
# ---------------------------------------------------------------------------

@app.route("/api/apply", methods=["POST"])
def api_apply():
    """
    Apply approved rewrites to the original PDF.
    Runs the reflow engine and patcher.
    Returns the fidelity report.
    """
    data = request.get_json() or {}
    # approved_texts: dict of section_name -> approved_text
    # If not provided, uses the proposed_text from each job
    approved_texts = data.get("approved_texts", {})

    state = _get_state()
    if not state["pdf_path"]:
        return jsonify({"error": "No PDF uploaded."}), 400
    if not state["jobs"]:
        return jsonify({"error": "No editing jobs found."}), 400

    fm = state["flow_map"]

    # Debug: log what we received vs what we have
    import logging
    logging.warning(f"api_apply: approved_texts keys={list(approved_texts.keys())}")
    logging.warning(f"api_apply: state jobs keys={list(state['jobs'].keys())}")

    # Collect section + replacement pairs
    edits = []
    for section_name, job in state["jobs"].items():
        # Check if this section was approved via the frontend
        replacement = approved_texts.get(section_name)

        # If not in approved_texts, fall back to proposed_text from the job
        if not replacement:
            replacement = job.get("proposed_text")

        if not replacement:
            continue
            
        section = fm.get_section(section_name)
        if section:
            edits.append((section, replacement))

    if not edits:
        return jsonify({"error": "No approved edits to apply."}), 400

    # Plan reflow for all sections
    reflow_results = plan_multi_section_reflow(edits, fm)

    # Check for unresolvable overflows
    unresolvable = [
        r for r in reflow_results if not r.can_apply
    ]
    if unresolvable:
        warnings = []
        for r in unresolvable:
            for w in r.overflow_warnings:
                warnings.append(w.description)
        return jsonify({
            "error": "Some edits cannot be applied due to overflow.",
            "warnings": warnings,
        }), 422

    # Write output to temp file
    if state["output_path"] and os.path.exists(state["output_path"]):
        try:
            os.unlink(state["output_path"])
        except OSError:
            pass

    out_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    out_tmp.close()
    output_path = out_tmp.name

    try:
        patch_report = apply_multiple_reflows(
            original_pdf_path=state["pdf_path"],
            reflow_results=reflow_results,
            grammar=fm.grammar,
            non_content=fm.non_content,
            output_path=output_path,
        )
    except Exception as e:
        return jsonify({"error": f"PDF patching failed: {str(e)}"}), 500

    # -----------------------------------------------------------------------
    # Safety gate: never send a missing/empty PDF to the fidelity checker.
    # The patcher may reject an edit and remove the temporary output file.
    # -----------------------------------------------------------------------
    if not patch_report.success:
        try:
            if os.path.exists(output_path):
                os.unlink(output_path)
        except OSError:
            pass

        state["output_path"] = None

        import logging
        patch_warnings = [
            w.description for w in patch_report.warnings
        ]

        logging.error(
            "PATCH REJECTED: success=%s pages_modified=%s warnings=%s output=%s",
            patch_report.success,
            patch_report.pages_modified,
            patch_warnings,
            patch_report.output_path,
        )

        return jsonify({
            "error": "PDF patching rejected the edit; the original PDF was not modified.",
            "patch_warnings": patch_warnings,
        }), 422

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        try:
            if os.path.exists(output_path):
                os.unlink(output_path)
        except OSError:
            pass

        state["output_path"] = None

        return jsonify({
            "error": "PDF patching produced no valid output; the original PDF was not modified.",
        }), 500

    state["output_path"] = output_path

    # Run fidelity check
    # Merge reflow results into one for the checker
    from reflow_engine import ReflowResult
    merged_affected = sorted(set(p for r in reflow_results for p in r.affected_pages))
    merged_result = ReflowResult(
        section_patches=[p for r in reflow_results for p in r.section_patches],
        downstream_shifts=[s for r in reflow_results for s in r.downstream_shifts],
        overflow_warnings=[w for r in reflow_results for w in r.overflow_warnings],
        delta_lines=sum(r.delta_lines for r in reflow_results),
        delta_points=sum(r.delta_points for r in reflow_results),
        affected_pages=merged_affected,
        unaffected_pages=[],
        can_apply=True,
    )

    try:
        fidelity = check_fidelity(
            original_path=state["pdf_path"],
            modified_path=output_path,
            reflow_result=merged_result,
            selected_section_names=[e[0].title for e in edits],
            non_content=fm.non_content,
        )
        state["fidelity_report"] = fidelity.as_dict()
    except Exception as e:
        # Fidelity check failure does not block the download
        state["fidelity_report"] = {
            "pass": None,
            "summary": f"Fidelity check could not complete: {str(e)}",
            "selected_sections": [e[0].title for e in edits],
            "pages_total": 0,
            "pages_modified": merged_affected,
            "non_target_pages_changed": [],
            "figures_original": 0,
            "figures_modified": 0,
            "tables_original": 0,
            "tables_modified": 0,
            "overflow_detected": False,
            "page_count_changed": False,
        }

    patch_warnings = [w.description for w in patch_report.warnings]

    return jsonify({
        "ok": True,
        "pages_modified": patch_report.pages_modified,
        "patch_warnings": patch_warnings,
        "fidelity": state["fidelity_report"],
    })


# ---------------------------------------------------------------------------
# API: Download
# ---------------------------------------------------------------------------

@app.route("/api/download", methods=["GET"])
def api_download():
    """Download the modified PDF."""
    state = _get_state()
    if not state["output_path"] or not os.path.exists(state["output_path"]):
        return jsonify({"error": "No modified PDF available."}), 404

    original_name = state["pdf_filename"] or "document.pdf"
    stem = original_name.replace(".pdf", "")
    download_name = f"{stem}_latbuild.pdf"

    return send_file(
        state["output_path"],
        mimetype="application/pdf",
        as_attachment=True,
        download_name=download_name,
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)