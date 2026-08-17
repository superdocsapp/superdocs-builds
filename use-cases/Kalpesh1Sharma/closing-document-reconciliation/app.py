from __future__ import annotations

import hashlib
import html
import json
import re
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import streamlit as st
from core.corrections import render_correction_request
from core.docx_render import markdown_to_docx_bytes
from core.extraction import build_extracted_document
from core.html_extraction import extract_from_superdocs_html
from core.memo import render_reconciliation_memo
from core.models import (
    DocumentType,
    ExtractedMortgageDocument,
)
from core.workflow import build_reconciliation_report
from superdocs.client import (
    SuperDocsClient,
    SuperDocsError,
)


# ============================================================
# CONFIGURATION
# ============================================================

EXPECTED_DOCUMENT_COUNT = 5
JOB_TIMEOUT_SECONDS = 180
POLL_INTERVAL_SECONDS = 2.0

EXPECTED_DOCUMENT_TYPES = {
    DocumentType.LOAN_ESTIMATE,
    DocumentType.CLOSING_DISCLOSURE,
    DocumentType.PROMISSORY_NOTE,
    DocumentType.SETTLEMENT_STATEMENT,
    DocumentType.UNDERWRITING_APPROVAL,
}


st.set_page_config(
    page_title="Closing Document Reconciliation",
    page_icon="📄",
    layout="wide",
)


# ============================================================
# SESSION STATE
# ============================================================


def initialize_state() -> None:
    defaults = {
        "processing_complete": False,
        "mortgage_session_id": None,
        "extracted_documents": {},
        "document_artifacts": {},
        "reconciliation_report": None,
        "memo_text": None,
        "correction_text": None,
        "memo_docx_bytes": None,
        "correction_docx_bytes": None,

        # Read-only Search / Chat surface
        "chat_history": [],

        # Review workflow
        "review_session_id": None,
        "review_job_id": None,
        "review_status": None,
        "review_pending_changes": [],
        "review_result": None,
        "review_artifact_name": None,
        "review_filename": None,
        "review_export_bytes": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


initialize_state()


def reset_processing_state() -> None:
    st.session_state.processing_complete = False
    st.session_state.mortgage_session_id = None
    st.session_state.extracted_documents = {}
    st.session_state.document_artifacts = {}
    st.session_state.reconciliation_report = None
    st.session_state.memo_text = None
    st.session_state.correction_text = None
    st.session_state.memo_docx_bytes = None
    st.session_state.correction_docx_bytes = None
    st.session_state.chat_history = []

    reset_review_state()


def reset_review_state() -> None:
    st.session_state.review_session_id = None
    st.session_state.review_job_id = None
    st.session_state.review_status = None
    st.session_state.review_pending_changes = []
    st.session_state.review_result = None
    st.session_state.review_artifact_name = None
    st.session_state.review_filename = None
    st.session_state.review_export_bytes = None


# ============================================================
# GENERAL HELPERS
# ============================================================


def uploaded_file_hash(uploaded_file) -> str:
    return hashlib.sha256(
        uploaded_file.getvalue()
    ).hexdigest()


def save_uploaded_file(
    uploaded_file,
    directory: Path,
) -> Path:
    path = directory / uploaded_file.name

    path.write_bytes(
        uploaded_file.getvalue()
    )

    return path


def clean_html_text(value: str | None) -> str:
    """
    Convert uploaded-document HTML into a simplified text form
    for lightweight grounding validation.
    """

    if not value:
        return ""

    text = re.sub(
        r"<[^>]+>",
        " ",
        value,
    )

    text = html.unescape(text)

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def normalize_grounding_text(
    value: str | None,
) -> str:
    if value is None:
        return ""

    return re.sub(
        r"[^a-z0-9]+",
        "",
        str(value).lower(),
    )


def raw_value_is_grounded(
    raw_value,
    document_html: str | None,
) -> bool:
    """
    Lightweight cross-document leakage check.

    A non-null extracted raw value should occur in the actual
    targeted document content after punctuation/whitespace
    normalization.

    This is evidence validation, not semantic inference.
    """

    if raw_value is None:
        return True

    document_text = clean_html_text(
        document_html
    )

    needle = normalize_grounding_text(
        str(raw_value)
    )

    haystack = normalize_grounding_text(
        document_text
    )

    if not needle:
        return True

    return needle in haystack


def validate_document_grounding(
    document: ExtractedMortgageDocument,
    source_html: str | None,
) -> list[str]:
    """
    Validate extracted values, evidence quotes, and file rules against
    the exact targeted document. Unsupported material is reported
    rather than inferred or substituted.
    """

    if not source_html:
        return [
            (
                "Source document HTML was unavailable, so "
                "extraction grounding could not be verified."
            )
        ]

    warnings: list[str] = []

    checks = {
        "borrower_names": document.borrower_names,
        "property_address": document.property_address,
        "loan_amount": document.loan_amount,
        "interest_rate": document.interest_rate,
        "term_months": document.term_months,
        "escrow": document.escrow,
        "cash_to_close": document.cash_to_close,
    }

    for fee_name, evidence in document.fees.items():
        checks[f"fees.{fee_name}"] = evidence

    for field_name, evidence in checks.items():
        if (
            evidence.raw_value is not None
            and not raw_value_is_grounded(
                evidence.raw_value,
                source_html,
            )
        ):
            warnings.append(
                (
                    f"{field_name}: extracted raw value "
                    f"{evidence.raw_value!r} was not found "
                    "in the targeted document."
                )
            )

        if (
            evidence.supporting_quote
            and not raw_value_is_grounded(
                evidence.supporting_quote,
                source_html,
            )
        ):
            warnings.append(
                (
                    f"{field_name}: supporting quote could not "
                    "be verified in the targeted document."
                )
            )

    for rule in document.rules:
        if not raw_value_is_grounded(
            rule.supporting_quote,
            source_html,
        ):
            warnings.append(
                (
                    f"Rule {rule.rule_id}: supporting quote could "
                    "not be verified in the targeted document."
                )
            )

    return warnings


def get_superdocs_client() -> SuperDocsClient | None:
    try:
        return SuperDocsClient()

    except Exception as exc:
        st.error(
            f"SuperDocs configuration error: {exc}"
        )

        return None


def format_value(value) -> str:
    if value is None:
        return "Not found"

    if isinstance(value, bool):
        return "Yes" if value else "No"

    if isinstance(value, float):
        if value.is_integer():
            return f"{value:,.0f}"

        return (
            f"{value:,.3f}"
            .rstrip("0")
            .rstrip(".")
        )

    return str(value)


# ============================================================
# EXTRACTION WORKFLOW
# ============================================================

# HTML parsing and document-type inference live in
# core/html_extraction.py. Keeping that logic outside Streamlit makes
# it independently testable and keeps this file focused on workflow/UI.


def process_documents(
    uploaded_files,
) -> None:
    if len(uploaded_files) != EXPECTED_DOCUMENT_COUNT:
        st.error(
            (
                "This build expects exactly "
                f"{EXPECTED_DOCUMENT_COUNT} documents."
            )
        )
        return

    client = get_superdocs_client()

    if client is None:
        return

    reset_processing_state()

    main_session_id = (
        "mortgage-reconciliation-"
        + uuid4().hex[:10]
    )

    st.session_state.mortgage_session_id = (
        main_session_id
    )

    progress = st.progress(0)
    status_box = st.empty()

    extracted_documents = {}
    document_artifacts = {}
    uploaded_document_records = []

    # PHASE 1 — open all five in one SuperDocs session.
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        for index, uploaded_file in enumerate(
            uploaded_files,
            start=1,
        ):
            progress.progress(
                int(
                    (
                        index - 1
                    )
                    / (
                        EXPECTED_DOCUMENT_COUNT
                        * 2
                    )
                    * 100
                )
            )

            status_box.info(
                (
                    f"Opening {uploaded_file.name} "
                    "in the shared SuperDocs session "
                    f"({index}/{EXPECTED_DOCUMENT_COUNT})..."
                )
            )

            file_bytes = (
                uploaded_file.getvalue()
            )

            local_path = (
                temp_path
                / uploaded_file.name
            )

            local_path.write_bytes(
                file_bytes
            )

            open_mode = (
                "replace"
                if index == 1
                else "background"
            )

            try:
                upload_result = (
                    client.upload_document(
                        path=local_path,
                        session_id=main_session_id,
                        open_mode=open_mode,
                    )
                )

            except Exception as exc:
                st.error(
                    (
                        f"Upload failed for "
                        f"{uploaded_file.name}: {exc}"
                    )
                )
                return

            document_id = (
                upload_result.get(
                    "document_id"
                )
            )

            source_html = (
                upload_result.get(
                    "html"
                )
            )

            if not document_id:
                st.error(
                    (
                        "SuperDocs did not return a "
                        f"document_id for "
                        f"{uploaded_file.name}."
                    )
                )
                return

            if not source_html:
                st.error(
                    (
                        "SuperDocs uploaded "
                        f"{uploaded_file.name} but returned "
                        "no processed HTML, so the document "
                        "cannot be grounded safely."
                    )
                )
                return

            uploaded_document_records.append({
                "filename":
                    uploaded_file.name,

                "main_document_id":
                    document_id,

                "source_html":
                    source_html,

                "file_hash":
                    hashlib.sha256(
                        file_bytes
                    ).hexdigest(),
            })

    # Verify the shared multi-document workspace.
    try:
        roster = (
            client.list_session_documents(
                session_id=main_session_id
            )
        )

    except Exception as exc:
        st.error(
            (
                "The files were uploaded, but the "
                "shared SuperDocs session could not "
                f"be verified: {exc}"
            )
        )
        return

    roster_documents = (
        roster.get("documents")
        or []
    )

    if (
        len(roster_documents)
        != EXPECTED_DOCUMENT_COUNT
    ):
        st.error(
            (
                "Shared session verification failed. "
                f"Expected {EXPECTED_DOCUMENT_COUNT} "
                "open documents but SuperDocs reported "
                f"{len(roster_documents)}."
            )
        )
        return

    # PHASE 2 — deterministic extraction from SuperDocs HTML.
    for index, record in enumerate(
        uploaded_document_records,
        start=1,
    ):
        filename = (
            record["filename"]
        )

        progress.progress(
            int(
                (
                    EXPECTED_DOCUMENT_COUNT
                    + index
                )
                / (
                    EXPECTED_DOCUMENT_COUNT
                    * 2
                )
                * 100
            )
        )

        status_box.info(
            (
                "Extracting grounded fields from "
                f"{filename} "
                f"({index}/{EXPECTED_DOCUMENT_COUNT})..."
            )
        )

        source_html = (
            record["source_html"]
        )

        try:
            raw_extraction = (
                extract_from_superdocs_html(
                    filename=filename,
                    document_html=source_html,
                )
            )

            canonical = (
                build_extracted_document(
                    filename=filename,
                    raw=raw_extraction,
                )
            )

        except Exception as exc:
            st.error(
                (
                    "Deterministic extraction failed "
                    f"for {filename}: {exc}"
                )
            )
            return

        document_type = (
            canonical.document_type
        )

        if (
            document_type
            == DocumentType.UNKNOWN
        ):
            st.error(
                (
                    "Could not determine the document "
                    f"type for {filename}."
                )
            )
            return

        if (
            document_type
            in extracted_documents
        ):
            existing = (
                extracted_documents[
                    document_type
                ].filename
            )

            st.error(
                (
                    "Duplicate document type detected: "
                    f"{document_type.value}. "
                    f"Files: {existing} and {filename}."
                )
            )
            return

        grounding_warnings = (
            validate_document_grounding(
                canonical,
                source_html,
            )
        )

        if grounding_warnings:
            st.error(
                (
                    "Grounding validation failed for "
                    f"{filename}. The extracted evidence "
                    "will not be used for reconciliation."
                )
            )

            with st.expander(
                "Grounding validation details",
                expanded=True,
            ):
                for warning in grounding_warnings:
                    st.warning(
                        warning
                    )

            st.warning(
                (
                    "Processing stopped rather than using "
                    "unsupported extracted values or rules."
                )
            )
            return

        extracted_documents[
            document_type
        ] = canonical

        document_artifacts[
            document_type.value
        ] = {
            "filename":
                filename,

            "main_document_id":
                record[
                    "main_document_id"
                ],

            "file_hash":
                record[
                    "file_hash"
                ],

            "raw_extraction":
                raw_extraction,

            "source_html":
                source_html,

            "grounding_warnings":
                [],

            "extraction_method":
                "deterministic_superdocs_html",
        }

    progress.progress(100)

    actual_types = set(
        extracted_documents.keys()
    )

    missing_types = (
        EXPECTED_DOCUMENT_TYPES
        - actual_types
    )

    unexpected_types = (
        actual_types
        - EXPECTED_DOCUMENT_TYPES
    )

    if missing_types:
        st.error(
            (
                "The uploaded mortgage file is missing "
                "these required document types: "
                + ", ".join(
                    sorted(
                        item.value
                        for item
                        in missing_types
                    )
                )
            )
        )
        return

    if unexpected_types:
        st.error(
            (
                "Unexpected document type(s): "
                + ", ".join(
                    sorted(
                        item.value
                        for item
                        in unexpected_types
                    )
                )
            )
        )
        return

    status_box.info(
        "Running deterministic reconciliation..."
    )

    report = build_reconciliation_report(
        documents=extracted_documents,
        scenario_id=(
            "LIVE-"
            + uuid4().hex[:8].upper()
        ),
    )

    report_dict = (
        report.model_dump(
            mode="json"
        )
    )

    memo_text = (
        render_reconciliation_memo(
            report_dict
        )
    )

    correction_text = (
        render_correction_request(
            report_dict
        )
    )

    st.session_state.extracted_documents = (
        extracted_documents
    )

    st.session_state.document_artifacts = (
        document_artifacts
    )

    st.session_state.reconciliation_report = (
        report_dict
    )

    st.session_state.memo_text = (
        memo_text
    )

    st.session_state.correction_text = (
        correction_text
    )

    st.session_state.memo_docx_bytes = (
        markdown_to_docx_bytes(
            memo_text
        )
    )

    st.session_state.correction_docx_bytes = (
        markdown_to_docx_bytes(
            correction_text
        )
    )

    st.session_state.processing_complete = True

    status_box.success(
        (
            "Reconciliation complete. "
            "All five documents remain open in the "
            "shared SuperDocs workspace. "
            "Field extraction used processed HTML "
            "returned by SuperDocs and required no "
            "AI extraction chat calls."
        )
    )




# ============================================================
# SEARCH / CHAT HELPERS
# ============================================================


def search_grounded_documents(
    query: str,
) -> list[dict[str, str]]:
    """Search the processed SuperDocs HTML without another API call."""

    query = query.strip()

    if not query:
        return []

    terms = [
        term.casefold()
        for term in re.findall(
            r"[A-Za-z0-9$%.,/-]+",
            query,
        )
        if term.strip()
    ]

    if not terms:
        return []

    results: list[dict[str, str]] = []

    for artifact in (
        st.session_state.document_artifacts.values()
    ):
        source_html = artifact.get(
            "source_html",
            "",
        )

        document_text = clean_html_text(
            source_html
        )

        lowered = document_text.casefold()

        positions = [
            lowered.find(term)
            for term in terms
        ]

        if any(
            position < 0
            for position in positions
        ):
            continue

        first_position = min(
            position
            for position in positions
            if position >= 0
        )

        snippet_start = max(
            0,
            first_position - 140,
        )

        snippet_end = min(
            len(document_text),
            first_position + 360,
        )

        snippet = (
            document_text[
                snippet_start:
                snippet_end
            ]
            .strip()
        )

        if snippet_start > 0:
            snippet = "…" + snippet

        if snippet_end < len(document_text):
            snippet = snippet + "…"

        results.append({
            "filename": artifact.get(
                "filename",
                "unknown document",
            ),
            "snippet": snippet,
        })

    return results


def send_read_only_chat(
    *,
    question: str,
    scope_label: str,
) -> None:
    """Send a non-authoritative read-only question to SuperDocs chat."""

    question = question.strip()

    if not question:
        st.warning(
            "Enter a question first."
        )
        return

    session_id = (
        st.session_state.mortgage_session_id
    )

    if not session_id:
        st.error(
            "Process a mortgage file before using chat."
        )
        return

    client = get_superdocs_client()

    if client is None:
        return

    prompt = (
        "Read-only question. Do not edit, rewrite, or modify any "
        "document. Answer only from the currently open mortgage "
        "file. If the answer is not supported by the open documents, "
        "say that it is not found in the file.\n\n"
        f"Question: {question}"
    )

    kwargs = {
        "session_id": session_id,
        "message": prompt,
    }

    if scope_label != "All open documents":
        selected_artifact = next(
            (
                artifact
                for artifact in (
                    st.session_state.document_artifacts.values()
                )
                if artifact.get("filename")
                == scope_label
            ),
            None,
        )

        if not selected_artifact:
            st.error(
                "Could not resolve the selected document."
            )
            return

        kwargs["document_id"] = (
            selected_artifact.get(
                "main_document_id"
            )
        )

    try:
        result = client.chat(
            **kwargs
        )

    except TypeError as exc:
        if scope_label == "All open documents":
            st.error(
                "This SuperDocs client requires a specific document "
                "for chat. Choose one of the five documents and retry."
            )
            return

        st.error(
            f"SuperDocs chat call failed: {exc}"
        )
        return

    except Exception as exc:
        st.error(
            f"SuperDocs chat failed: {exc}"
        )
        return

    response = (
        result.get("response")
        if isinstance(result, dict)
        else None
    )

    if not response:
        response = (
            result.get("message")
            if isinstance(result, dict)
            else None
        )

    if not response:
        try:
            response = json.dumps(
                result,
                indent=2,
                default=str,
            )
        except Exception:
            response = str(result)

    st.session_state.chat_history.append({
        "question": question,
        "scope": scope_label,
        "response": response,
    })


# ============================================================
# REVIEW WORKFLOW
# ============================================================


def poll_review_job(
    client: SuperDocsClient,
    job_id: str,
) -> dict:
    status_placeholder = st.empty()

    started = time.monotonic()
    last_status = None

    while True:
        job = client.get_job(
            job_id=job_id
        )

        status = job.get(
            "status"
        )

        if status != last_status:
            status_placeholder.info(
                f"SuperDocs job status: {status}"
            )
            last_status = status

        if status in {
            "awaiting_approval",
            "completed",
        }:
            return job

        if status == "failed":
            raise SuperDocsError(
                job.get(
                    "error",
                    "SuperDocs review job failed.",
                )
            )

        if status == "cancelled":
            raise SuperDocsError(
                "SuperDocs review job was cancelled."
            )

        elapsed = (
            time.monotonic()
            - started
        )

        if elapsed >= JOB_TIMEOUT_SECONDS:
            raise TimeoutError(
                (
                    "SuperDocs review did not reach an "
                    "actionable state within "
                    f"{JOB_TIMEOUT_SECONDS} seconds."
                )
            )

        if elapsed >= 30:
            status_placeholder.info(
                (
                    "SuperDocs is still processing. "
                    f"{int(elapsed)} seconds elapsed."
                )
            )

        time.sleep(
            POLL_INTERVAL_SECONDS
        )


def parse_pending_changes(value) -> list[dict]:
    """
    SuperDocs may return pending changes directly as a list or as a
    JSON-encoded string. Parse the second encoding defensively and
    fail rather than guessing.
    """

    if value is None:
        return []

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SuperDocsError(
                (
                    "SuperDocs returned pending changes as a string "
                    "that was not valid JSON."
                )
            ) from exc

    if isinstance(value, dict):
        candidate = (
            value.get("pending_changes")
            or value.get("changes")
        )

        if candidate is not None:
            value = candidate

            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise SuperDocsError(
                        "Nested pending changes were not valid JSON."
                    ) from exc

    if not isinstance(value, list):
        raise SuperDocsError(
            (
                "Expected SuperDocs pending changes to be a list, "
                f"got {type(value).__name__}."
            )
        )

    parsed_changes = []

    for change in value:
        if isinstance(change, str):
            try:
                change = json.loads(change)
            except json.JSONDecodeError as exc:
                raise SuperDocsError(
                    (
                        "A proposed change was JSON-encoded but "
                        "could not be parsed."
                    )
                ) from exc

        if not isinstance(change, dict):
            raise SuperDocsError(
                "A proposed change was not an object."
            )

        # SuperDocs may encode proposed-change content as JSON inside
        # a string. Preserve the original field but expose the parsed
        # representation when that second parse is applicable.
        content = change.get("content")

        if isinstance(content, str):
            stripped = content.strip()

            if stripped.startswith(("{", "[")):
                try:
                    change["content_parsed"] = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise SuperDocsError(
                        (
                            "A proposed change contained JSON-encoded "
                            "content that could not be parsed."
                        )
                    ) from exc

        parsed_changes.append(change)

    return parsed_changes


def start_review(
    *,
    artifact_name: str,
    instruction: str,
) -> None:
    if not instruction.strip():
        st.error(
            "Enter an edit instruction first."
        )
        return

    client = get_superdocs_client()

    if client is None:
        return

    if artifact_name == "Reconciliation Memo":
        file_bytes = (
            st.session_state.memo_docx_bytes
        )

        filename = (
            "reconciliation_memo.docx"
        )

    else:
        file_bytes = (
            st.session_state.correction_docx_bytes
        )

        filename = (
            "correction_request.docx"
        )

    if not file_bytes:
        st.error(
            "The selected artifact has not been generated."
        )
        return

    reset_review_state()

    review_session_id = (
        "review-"
        + uuid4().hex[:10]
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        path = (
            Path(temp_dir)
            / filename
        )

        path.write_bytes(
            file_bytes
        )

        with st.spinner(
            "Uploading artifact to SuperDocs Review..."
        ):
            client.upload_document(
                path=path,
                session_id=review_session_id,
                open_mode="replace",
            )

        with st.spinner(
            "Generating proposed changes..."
        ):
            started = client.start_async_chat(
                session_id=review_session_id,
                message=instruction,
                approval_mode="ask_every_time",
            )

    job_id = started.get(
        "job_id"
    )

    if not job_id:
        st.error(
            "SuperDocs did not return a review job ID."
        )
        return

    st.session_state.review_session_id = (
        review_session_id
    )

    st.session_state.review_job_id = (
        job_id
    )

    st.session_state.review_artifact_name = (
        artifact_name
    )

    st.session_state.review_filename = (
        filename
    )

    try:
        job = poll_review_job(
            client,
            job_id,
        )

    except Exception as exc:
        st.error(
            f"Review job failed: {exc}"
        )
        return

    st.session_state.review_status = (
        job.get("status")
    )

    if (
        job.get("status")
        == "awaiting_approval"
    ):
        metadata = (
            job.get("metadata")
            or {}
        )

        awaiting_kind = metadata.get(
            "awaiting_kind"
        )

        if awaiting_kind == "continue_prompt":
            st.error(
                (
                    "SuperDocs requested continuation for "
                    "a large edit. Use a smaller, surgical "
                    "edit instruction for this build."
                )
            )
            return

        try:
            st.session_state.review_pending_changes = (
                parse_pending_changes(
                    metadata.get(
                        "pending_changes"
                    )
                )
            )

        except SuperDocsError as exc:
            st.error(
                f"Could not parse proposed changes: {exc}"
            )
            return

    elif job.get("status") == "completed":
        st.session_state.review_result = (
            job.get("result")
            or {}
        )


def submit_review_decision(
    approved: bool,
) -> None:
    client = get_superdocs_client()

    if client is None:
        return

    job_id = st.session_state.review_job_id
    session_id = (
        st.session_state.review_session_id
    )

    pending_changes = (
        st.session_state.review_pending_changes
    )

    if (
        not job_id
        or not session_id
        or not pending_changes
    ):
        st.error(
            "There are no proposed changes to review."
        )
        return

    decisions = [
        {
            "change_id":
                change["change_id"],
            "approved":
                approved,
        }
        for change in pending_changes
        if change.get("change_id")
    ]

    if not decisions:
        st.error(
            "SuperDocs returned no usable change IDs."
        )
        return

    try:
        client.approve_changes(
            session_id=session_id,
            job_id=job_id,
            approved=approved,
            changes=decisions,
        )

        with st.spinner(
            "Applying human decision..."
        ):
            job = poll_review_job(
                client,
                job_id,
            )

    except Exception as exc:
        st.error(
            f"Could not submit decision: {exc}"
        )
        return

    st.session_state.review_status = (
        job.get("status")
    )

    st.session_state.review_pending_changes = []

    if job.get("status") == "completed":
        st.session_state.review_result = (
            job.get("result")
            or {}
        )

        if approved:
            st.success(
                "Approved change(s) were applied."
            )
        else:
            st.info(
                "Proposed change(s) were rejected."
            )


def export_reviewed_document() -> None:
    client = get_superdocs_client()

    if client is None:
        return

    session_id = (
        st.session_state.review_session_id
    )

    if not session_id:
        st.error(
            "No reviewed document session exists."
        )
        return

    with tempfile.TemporaryDirectory() as temp_dir:
        output_path = (
            Path(temp_dir)
            / "reviewed_document.docx"
        )

        try:
            client.export_document(
                session_id=session_id,
                output_path=output_path,
                filename="reviewed_document",
                file_format="docx",
            )

        except Exception as exc:
            st.error(
                f"Export failed: {exc}"
            )
            return

        st.session_state.review_export_bytes = (
            output_path.read_bytes()
        )

    st.success(
        "Reviewed document exported successfully."
    )


# ============================================================
# HEADER
# ============================================================

st.title(
    "Closing Document Reconciliation"
)

st.caption(
    (
        "SuperDocs document ingestion with deterministic field "
        "extraction, file-derived variance rules, human review, "
        "and DOCX export."
    )
)

st.info(
    (
        "Demo build only. It uses rules contained in the "
        "uploaded file and does not apply external mortgage "
        "law or regulatory assumptions."
    )
)


# ============================================================
# TABS
# ============================================================

(
    tab_documents,
    tab_reconciliation,
    tab_memo,
    tab_search_chat,
    tab_review,
    tab_export,
) = st.tabs([
    "1 · Documents",
    "2 · Reconciliation",
    "3 · Memo & Correction",
    "4 · Search & Chat",
    "5 · Review",
    "6 · Export",
])


# ============================================================
# TAB 1 — DOCUMENTS
# ============================================================

with tab_documents:
    st.header(
        "Mortgage file"
    )

    st.write(
        (
            "Upload the five documents for one closing file. "
            "They are opened together in one SuperDocs session."
        )
    )

    uploaded_files = st.file_uploader(
        "Upload exactly five DOCX or PDF files",
        type=[
            "docx",
            "pdf",
        ],
        accept_multiple_files=True,
    )

    if uploaded_files:
        st.write(
            f"Selected: {len(uploaded_files)} / "
            f"{EXPECTED_DOCUMENT_COUNT}"
        )

        for uploaded_file in uploaded_files:
            st.write(
                f"• {uploaded_file.name}"
            )

    col_process, col_reset = st.columns(
        [1, 1]
    )

    with col_process:
        if st.button(
            "Process documents",
            type="primary",
            disabled=(
                not uploaded_files
                or len(uploaded_files)
                != EXPECTED_DOCUMENT_COUNT
                or st.session_state.processing_complete
            ),
        ):
            process_documents(
                uploaded_files
            )

    with col_reset:
        if st.button(
            "Reset file",
        ):
            reset_processing_state()
            st.rerun()

    if st.session_state.processing_complete:
        st.success(
            "File processed successfully."
        )

        st.write(
            "**Detected document types**"
        )

        for doc_type, document in (
            st.session_state.extracted_documents.items()
        ):
            artifact = (
                st.session_state.document_artifacts.get(
                    doc_type.value,
                    {},
                )
            )

            warnings = artifact.get(
                "grounding_warnings",
                [],
            )

            if warnings:
                icon = "⚠️"
            else:
                icon = "✅"

            st.write(
                (
                    f"{icon} "
                    f"`{document.filename}` → "
                    f"**{doc_type.value}**"
                )
            )

            if warnings:
                with st.expander(
                    (
                        f"Grounding warnings — "
                        f"{document.filename}"
                    )
                ):
                    for warning in warnings:
                        st.warning(
                            warning
                        )

        with st.expander(
            "Extraction evidence"
        ):
            for doc_type, document in (
                st.session_state.extracted_documents.items()
            ):
                st.subheader(
                    document.filename
                )

                st.json(
                    document.model_dump(
                        mode="json"
                    )
                )




# ============================================================
# TAB 2 — RECONCILIATION
# ============================================================

with tab_reconciliation:
    st.header(
        "Reconciliation results"
    )

    report = (
        st.session_state.reconciliation_report
    )

    if not report:
        st.info(
            "Process a mortgage file first."
        )

    else:
        findings = report.get(
            "findings",
            [],
        )

        matches = sum(
            1
            for finding in findings
            if finding["status"] == "match"
        )

        tolerable = sum(
            1
            for finding in findings
            if (
                finding["classification"]
                == "tolerable"
            )
        )

        curable = sum(
            1
            for finding in findings
            if (
                finding["classification"]
                == "curable"
            )
        )

        unresolved = sum(
            1
            for finding in findings
            if finding["classification"]
            == "unclassified"
        )

        c1, c2, c3, c4 = st.columns(4)

        c1.metric(
            "Matches",
            matches,
        )

        c2.metric(
            "Tolerable",
            tolerable,
        )

        c3.metric(
            "Curable",
            curable,
        )

        c4.metric(
            "Unresolved",
            unresolved,
        )

        if curable:
            st.warning(
                (
                    f"{curable} curable variance(s) "
                    "require human review under the "
                    "file-specific rules."
                )
            )

        for finding in findings:
            field_name = (
                finding["field_name"]
                .replace("_", " ")
                .title()
            )

            status = (
                finding["status"]
                .replace("_", " ")
                .title()
            )

            classification = (
                finding["classification"]
                .replace("_", " ")
                .title()
            )

            if (
                finding["classification"]
                == "curable"
            ):
                icon = "🔴"

            elif (
                finding["classification"]
                == "tolerable"
            ):
                icon = "🟠"

            elif finding["status"] == "match":
                icon = "🟢"

            else:
                icon = "⚪"

            with st.expander(
                (
                    f"{icon} {field_name} — "
                    f"{status} / {classification}"
                ),
                expanded=(
                    finding["status"]
                    != "match"
                ),
            ):
                observations = finding.get(
                    "observations",
                    [],
                )

                if observations:
                    rows = []

                    for obs in observations:
                        rows.append({
                            "Document":
                                obs["filename"],
                            "Value":
                                format_value(
                                    obs.get(
                                        "value"
                                    )
                                ),
                            "Source value":
                                obs.get(
                                    "raw_value"
                                ),
                            "Evidence":
                                obs.get(
                                    "supporting_quote"
                                ),
                        })

                    st.dataframe(
                        rows,
                        use_container_width=True,
                        hide_index=True,
                    )

                rule = finding.get(
                    "applicable_rule"
                )

                if rule:
                    st.write(
                        "**File rule**"
                    )

                    st.code(
                        (
                            f"{rule['rule_id']}: "
                            f"{rule['rule_text']}"
                        ),
                        language=None,
                    )

                st.write(
                    "**Explanation**"
                )

                st.write(
                    finding.get(
                        "explanation",
                        ""
                    )
                )

                if finding.get(
                    "recommended_action"
                ):
                    st.write(
                        "**Recommended action**"
                    )

                    st.write(
                        finding[
                            "recommended_action"
                        ]
                    )

        warnings = report.get(
            "warnings",
            [],
        )

        if warnings:
            with st.expander(
                "Workflow warnings"
            ):
                for warning in warnings:
                    st.warning(
                        warning
                    )


# ============================================================
# TAB 3 — MEMO + CORRECTION
# ============================================================

with tab_memo:
    st.header(
        "Generated work product"
    )

    if not st.session_state.memo_text:
        st.info(
            "Process and reconcile a mortgage file first."
        )

    else:
        artifact_tab_1, artifact_tab_2 = (
            st.tabs([
                "Reconciliation Memo",
                "Correction Request",
            ])
        )

        with artifact_tab_1:
            st.markdown(
                st.session_state.memo_text
            )

        with artifact_tab_2:
            st.markdown(
                st.session_state.correction_text
            )


# ============================================================
# TAB 4 — SEARCH + CHAT
# ============================================================

with tab_search_chat:
    st.header(
        "Search & Chat"
    )

    if not st.session_state.processing_complete:
        st.info(
            "Process a mortgage file first."
        )

    else:
        st.subheader(
            "Grounded search"
        )

        st.caption(
            "Search runs locally over the processed HTML returned by "
            "SuperDocs and does not consume another chat operation."
        )

        search_query = st.text_input(
            "Search the open mortgage file",
            placeholder=(
                "Example: cash to close, approved note rate, "
                "John Carter"
            ),
            key="grounded_search_query",
        )

        if search_query.strip():
            search_results = (
                search_grounded_documents(
                    search_query
                )
            )

            if not search_results:
                st.info(
                    "No grounded matches were found in the five documents."
                )

            else:
                st.write(
                    f"Found {len(search_results)} matching document(s)."
                )

                for result in search_results:
                    with st.expander(
                        result["filename"],
                        expanded=True,
                    ):
                        st.write(
                            result["snippet"]
                        )

        st.divider()

        st.subheader(
            "Read-only SuperDocs chat"
        )

        st.caption(
            "Chat is exploratory only. Reconciliation classifications "
            "come from deterministic extraction and file-specific rules, "
            "not from chat responses."
        )

        filenames = sorted(
            artifact.get(
                "filename",
                "",
            )
            for artifact in (
                st.session_state.document_artifacts.values()
            )
            if artifact.get("filename")
        )

        chat_scope = st.selectbox(
            "Chat scope",
            [
                "All open documents",
                *filenames,
            ],
        )

        if chat_scope == "All open documents":
            st.caption(
                "The SuperDocs chat router may occasionally ask for a "
                "more specific target. If that happens, select one document."
            )

        chat_question = st.text_area(
            "Question",
            placeholder=(
                "Example: What approved interest rate appears in this file?"
            ),
            height=100,
        )

        if st.button(
            "Ask SuperDocs",
            type="primary",
        ):
            send_read_only_chat(
                question=chat_question,
                scope_label=chat_scope,
            )

        if st.session_state.chat_history:
            st.subheader(
                "Chat history"
            )

            for item in reversed(
                st.session_state.chat_history
            ):
                with st.expander(
                    (
                        f"{item['scope']} — "
                        f"{item['question']}"
                    ),
                    expanded=True,
                ):
                    st.write(
                        item["response"]
                    )


# ============================================================
# TAB 5 — HUMAN REVIEW
# ============================================================

with tab_review:
    st.header(
        "SuperDocs Review"
    )

    if not st.session_state.memo_text:
        st.info(
            "Generate the reconciliation artifacts first."
        )

    else:
        artifact_name = st.selectbox(
            "Artifact to edit",
            [
                "Reconciliation Memo",
                "Correction Request",
            ],
        )

        edit_instruction = st.text_area(
            "Edit instruction",
            placeholder=(
                "Example: Change the heading "
                "'Executive Summary' to "
                "'Reconciliation Summary'. "
                "Do not alter any values or findings."
            ),
            height=120,
        )

        if st.button(
            "Send to Review",
            type="primary",
        ):
            start_review(
                artifact_name=artifact_name,
                instruction=edit_instruction,
            )

        pending_changes = (
            st.session_state.review_pending_changes
        )

        if pending_changes:
            st.subheader(
                "Proposed changes"
            )

            st.warning(
                (
                    "Nothing has been applied yet. "
                    "Review the proposed edits before "
                    "approving them."
                )
            )

            for index, change in enumerate(
                pending_changes,
                start=1,
            ):
                with st.expander(
                    f"Proposed change {index}",
                    expanded=True,
                ):
                    st.write(
                        "**Operation:**",
                        change.get(
                            "operation",
                            "unknown",
                        ),
                    )

                    explanation = (
                        change.get(
                            "ai_explanation"
                        )
                    )

                    if explanation:
                        st.write(
                            "**AI explanation:**"
                        )

                        st.write(
                            explanation
                        )

                    old_html = change.get(
                        "old_html"
                    )

                    new_html = change.get(
                        "new_html"
                    )

                    if old_html:
                        st.write(
                            "**Before**"
                        )

                        st.code(
                            old_html,
                            language="html",
                        )

                    if new_html:
                        st.write(
                            "**After**"
                        )

                        st.code(
                            new_html,
                            language="html",
                        )

            approve_col, reject_col = (
                st.columns(2)
            )

            with approve_col:
                if st.button(
                    "Approve proposed changes",
                    type="primary",
                ):
                    submit_review_decision(
                        approved=True
                    )
                    st.rerun()

            with reject_col:
                if st.button(
                    "Reject proposed changes",
                ):
                    submit_review_decision(
                        approved=False
                    )
                    st.rerun()

        if (
            st.session_state.review_status
            == "completed"
        ):
            st.success(
                "Review workflow completed."
            )

            result = (
                st.session_state.review_result
                or {}
            )

            response_text = result.get(
                "response"
            )

            if response_text:
                st.write(
                    "**SuperDocs result**"
                )

                st.write(
                    response_text
                )


# ============================================================
# TAB 6 — EXPORT
# ============================================================

with tab_export:
    st.header(
        "Export"
    )

    if not st.session_state.processing_complete:
        st.info(
            "Process a mortgage file first."
        )

    else:
        st.subheader(
            "Generated artifacts"
        )

        col1, col2 = st.columns(2)

        with col1:
            st.download_button(
                "Download Reconciliation Memo",
                data=(
                    st.session_state.memo_docx_bytes
                ),
                file_name=(
                    "closing_document_"
                    "reconciliation_memo.docx"
                ),
                mime=(
                    "application/vnd.openxmlformats-"
                    "officedocument.wordprocessingml."
                    "document"
                ),
            )

        with col2:
            st.download_button(
                "Download Correction Request",
                data=(
                    st.session_state.correction_docx_bytes
                ),
                file_name=(
                    "revised_disclosure_"
                    "correction_request.docx"
                ),
                mime=(
                    "application/vnd.openxmlformats-"
                    "officedocument.wordprocessingml."
                    "document"
                ),
            )

        st.divider()

        st.subheader(
            "Reviewed SuperDocs artifact"
        )

        if (
            st.session_state.review_status
            != "completed"
        ):
            st.info(
                (
                    "Complete a SuperDocs Review workflow "
                    "before exporting the reviewed version."
                )
            )

        else:
            if st.button(
                "Export reviewed DOCX from SuperDocs",
                type="primary",
            ):
                export_reviewed_document()

            reviewed_bytes = (
                st.session_state.review_export_bytes
            )

            if reviewed_bytes:
                original_name = (
                    st.session_state.review_filename
                    or "reviewed_document.docx"
                )

                reviewed_name = (
                    Path(original_name).stem
                    + "_reviewed.docx"
                )

                st.download_button(
                    "Download reviewed DOCX",
                    data=reviewed_bytes,
                    file_name=reviewed_name,
                    mime=(
                        "application/vnd.openxmlformats-"
                        "officedocument.wordprocessingml."
                        "document"
                    ),
                )