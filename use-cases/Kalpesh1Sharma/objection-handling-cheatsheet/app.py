from __future__ import annotations
from uuid import uuid4

from superdocs.parser import (
    parse_pending_changes,
)
from superdocs.polling import (
    wait_until_action_needed,
)



import tempfile
from pathlib import Path

import streamlit as st

from core.cheatsheet import (
    build_cheatsheet_markdown,
    build_coverage_summary,
)
from core.docx_render import (
    build_cheatsheet_docx_bytes,
)
from core.html_input import (
    extract_lines_from_superdocs_html,
)
from core.models import EntryStatus
from core.parser import (
    parse_objection_notes,
)
from superdocs.client import (
    SuperDocsClient,
    SuperDocsError,
)


st.set_page_config(
    page_title="Objection Handling Cheatsheet",
    page_icon="📋",
    layout="wide",
)


def initialize_state() -> None:
    defaults = {
        "parse_result": None,
        "coverage": None,
        "source_filename": None,
        "session_id": None,
        "document_id": None,
        "source_html": None,
        "review_session_id": None,
        "review_document_id": None,
        "review_job_id": None,
        "pending_changes": [],
        "review_status": None,
        "review_decision": None,
        "chat_response": None,
        "reviewed_docx_bytes": None,
        }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def process_superdocs_upload(
    uploaded_file,
) -> None:
    suffix = Path(
        uploaded_file.name
    ).suffix

    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=suffix,
    ) as temp_file:
        temp_file.write(
            uploaded_file.getvalue()
        )

        temp_path = Path(
            temp_file.name
        )

    try:
        client = SuperDocsClient()

        session_id = (
            "objection-ui-"
            + __import__("uuid").uuid4().hex[:8]
        )

        upload = client.upload_document(
            path=temp_path,
            session_id=session_id,
            open_mode="replace",
        )

        html = upload.get(
            "html"
        )

        if not html:
            raise RuntimeError(
                "SuperDocs upload succeeded but "
                "returned no processed HTML."
            )

        lines = (
            extract_lines_from_superdocs_html(
                html
            )
        )

        result = parse_objection_notes(
            lines
        )

        coverage = (
            build_coverage_summary(
                result
            )
        )

        st.session_state.parse_result = (
            result
        )

        st.session_state.coverage = (
            coverage
        )

        st.session_state.source_filename = (
            uploaded_file.name
        )

        st.session_state.session_id = (
            upload.get("session_id")
            or session_id
        )

        st.session_state.document_id = (
            upload.get("document_id")
        )

        st.session_state.source_html = (
            html
        )

    finally:
        temp_path.unlink(
            missing_ok=True
        )

def prepare_generated_cheatsheet() -> None:
    result = st.session_state.parse_result

    if result is None:
        raise RuntimeError(
            "Generate a cheatsheet first."
        )

    docx_bytes = (
        build_cheatsheet_docx_bytes(
            result
        )
    )

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".docx",
        ) as temp_file:
            temp_file.write(
                docx_bytes
            )

            temp_path = Path(
                temp_file.name
            )

        client = SuperDocsClient()

        session_id = (
            "objection-ui-review-"
            + uuid4().hex[:8]
        )

        upload = client.upload_document(
            path=temp_path,
            session_id=session_id,
            open_mode="replace",
        )

        st.session_state.review_session_id = (
            upload.get("session_id")
            or session_id
        )

        st.session_state.review_document_id = (
            upload.get("document_id")
        )

        st.session_state.review_job_id = None
        st.session_state.pending_changes = []
        st.session_state.review_status = "ready"
        st.session_state.review_decision = None
        st.session_state.chat_response = None
        st.session_state.reviewed_docx_bytes = None

    finally:
        if temp_path is not None:
            temp_path.unlink(
                missing_ok=True
            )        


initialize_state()


st.title(
    "Objection Handling Cheatsheet Builder"
)

st.caption(
    "Turn messy objection-and-response notes "
    "into a clean, lossless sales cheatsheet."
)


(
    tab_input,
    tab_cheatsheet,
    tab_review,
    tab_export,
) = st.tabs(
    [
        "1 · Input & Coverage",
        "2 · Cheatsheet",
        "3 · Chat & Review",
        "4 · Export",
    ]
)

# ==========================================================
# TAB 1
# ==========================================================

with tab_input:
    st.subheader(
        "Upload messy sales notes"
    )

    st.write(
        "The source wording is preserved. "
        "Missing responses are flagged rather "
        "than generated."
    )

    uploaded_file = st.file_uploader(
        "Upload a DOCX file",
        type=[
            "docx",
        ],
    )

    if uploaded_file is not None:
        st.write(
            f"Selected: `{uploaded_file.name}`"
        )

        if st.button(
            "Process with SuperDocs",
            type="primary",
        ):
            try:
                with st.spinner(
                    "Uploading and processing "
                    "with SuperDocs..."
                ):
                    process_superdocs_upload(
                        uploaded_file
                    )

                st.success(
                    "Document processed successfully."
                )

            except (
                SuperDocsError,
                ValueError,
                RuntimeError,
            ) as exc:
                st.error(
                    str(exc)
                )

    result = (
        st.session_state.parse_result
    )

    coverage = (
        st.session_state.coverage
    )

    if (
        result is not None
        and coverage is not None
    ):
        st.divider()

        st.subheader(
            "Coverage audit"
        )

        col1, col2, col3, col4 = (
            st.columns(4)
        )

        col1.metric(
            "Detected objections",
            coverage[
                "detected_objections"
            ],
        )

        col2.metric(
            "Output blocks",
            coverage[
                "output_blocks"
            ],
        )

        col3.metric(
            "Complete responses",
            coverage[
                "complete_responses"
            ],
        )

        col4.metric(
            "Missing responses",
            coverage[
                "missing_responses"
            ],
        )

        col5, col6, col7 = (
            st.columns(3)
        )

        col5.metric(
            "Dropped objections",
            coverage[
                "dropped_objections"
            ],
        )

        col6.metric(
            "Duplicate assignments",
            coverage[
                "duplicate_assignments"
            ],
        )

        col7.metric(
            "Unassigned source items",
            coverage[
                "unassigned_source_items"
            ],
        )

        if coverage[
            "coverage_passed"
        ]:
            st.success(
                "Coverage passed — every detected "
                "objection has exactly one "
                "cheatsheet block."
            )
        else:
            st.error(
                "Coverage failed. Export is blocked."
            )

        st.subheader(
            "Source trace"
        )

        for entry in result.entries:
            with st.expander(
                (
                    f"{entry.entry_id} · "
                    f"{entry.objection}"
                )
            ):
                st.write(
                    "**Status:**",
                    entry.status.value,
                )

                st.write(
                    "**Objection source:**",
                    ", ".join(
                        entry.objection_source_ids
                    ),
                )

                st.write(
                    "**Response source:**",
                    (
                        ", ".join(
                            entry.response_source_ids
                        )
                        if entry.response_source_ids
                        else "None"
                    ),
                )


# ==========================================================
# TAB 2
# ==========================================================

with tab_cheatsheet:
    result = (
        st.session_state.parse_result
    )

    coverage = (
        st.session_state.coverage
    )

    if result is None:
        st.info(
            "Upload and process a document first."
        )

    elif not coverage[
        "coverage_passed"
    ]:
        st.error(
            "Coverage validation failed. "
            "Cheatsheet rendering is blocked."
        )

    else:
        st.subheader(
            "Generated cheatsheet"
        )

        st.caption(
            "One objection per block. "
            "No missing response is invented."
        )

        for index, entry in enumerate(
            result.entries,
            start=1,
        ):
            with st.container(
                border=True
            ):
                st.caption(
                    f"OBJECTION {index}"
                )

                st.markdown(
                    f"### {entry.objection}"
                )

                st.markdown(
                    "**Response**"
                )

                if (
                    entry.status
                    == EntryStatus.COMPLETE
                    and entry.response
                ):
                    st.write(
                        entry.response
                    )

                else:
                    st.warning(
                        "Missing response in "
                        "source notes — "
                        "human input required."
                    )

                source_ids = (
                    entry.objection_source_ids
                    + entry.response_source_ids
                )

                st.caption(
                    "Source: "
                    + ", ".join(
                        source_ids
                    )
                )

        st.divider()

        markdown_bytes = (
            build_cheatsheet_markdown(
                result
            ).encode("utf-8")
        )

        docx_bytes = (
            build_cheatsheet_docx_bytes(
                result
            )
        )

        col1, col2 = st.columns(2)

        col1.download_button(
            "Download Markdown",
            data=markdown_bytes,
            file_name="objection_handling_cheatsheet.md",
            mime="text/markdown",
            key="cheatsheet_tab_markdown_download",
        )

        col2.download_button(
            "Download DOCX",
            data=docx_bytes,
            file_name="objection_handling_cheatsheet.docx",
            mime=(
                "application/vnd.openxmlformats-"
                "officedocument.wordprocessingml.document"
            ),
            key="cheatsheet_tab_docx_download",
        )

# ==========================================================
# TAB 3
# ==========================================================

with tab_review:
    result = st.session_state.parse_result
    coverage = st.session_state.coverage

    if result is None:
        st.info(
            "Process a source document first."
        )

    elif not coverage["coverage_passed"]:
        st.error(
            "Coverage validation failed. "
            "Review is blocked."
        )

    else:
        st.subheader(
            "SuperDocs Chat & Human Review"
        )

        st.caption(
            "Chat is grounded in the generated cheatsheet. "
            "Edits require explicit human approval."
        )

        # --------------------------------------------------
        # Prepare generated cheatsheet
        # --------------------------------------------------

        if (
            st.session_state.review_session_id
            is None
        ):
            if st.button(
                "Open generated cheatsheet in SuperDocs",
                type="primary",
            ):
                try:
                    with st.spinner(
                        "Uploading generated cheatsheet..."
                    ):
                        prepare_generated_cheatsheet()

                    st.success(
                        "Generated cheatsheet opened "
                        "in SuperDocs."
                    )

                    st.rerun()

                except Exception as exc:
                    st.error(
                        str(exc)
                    )

        else:
            st.success(
                "Generated cheatsheet is ready "
                "in SuperDocs."
            )

            st.caption(
                "Session: "
                + str(
                    st.session_state.review_session_id
                )
            )

            # ==============================================
            # CHAT
            # ==============================================

            st.divider()

            st.subheader(
                "Grounded chat"
            )

            chat_question = st.text_area(
                "Ask about this cheatsheet",
                value=(
                    "Which objection in this cheatsheet "
                    "has no response? "
                    "Answer only from this document. "
                    "Do not edit the document."
                ),
                height=100,
            )

            if st.button(
                "Ask SuperDocs"
            ):
                try:
                    client = SuperDocsClient()

                    with st.spinner(
                        "Asking SuperDocs..."
                    ):
                        response = client.chat(
                            session_id=(
                                st.session_state
                                .review_session_id
                            ),
                            document_id=(
                                st.session_state
                                .review_document_id
                            ),
                            message=chat_question,
                        )

                    st.session_state.chat_response = (
                        response.get("response")
                        or response.get("message")
                        or str(response)
                    )

                except Exception as exc:
                    st.error(
                        str(exc)
                    )

            if st.session_state.chat_response:
                st.markdown(
                    "**SuperDocs response**"
                )

                st.info(
                    st.session_state.chat_response
                )

            # ==============================================
            # REVIEW
            # ==============================================

            st.divider()

            st.subheader(
                "Review an edit"
            )

            review_instruction = st.text_area(
                "Edit instruction",
                value=(
                    'Change the title '
                    '"Objection Handling Cheatsheet" '
                    'to "Sales Objection Handling '
                    'Cheatsheet".\n\n'
                    "Do not modify any objection text.\n"
                    "Do not modify any response text.\n"
                    "Do not fill in the missing response.\n"
                    "Do not add new sales claims.\n"
                    "Do not remove source references.\n"
                    "Do not make any other changes."
                ),
                height=200,
            )

            if (
                not st.session_state.pending_changes
                and st.session_state.review_status
                != "completed"
            ):
                if st.button(
                    "Start Review",
                    type="primary",
                ):
                    try:
                        client = SuperDocsClient()

                        with st.spinner(
                            "SuperDocs is preparing "
                            "proposed changes..."
                        ):
                            started = (
                                client.start_async_chat(
                                    session_id=(
                                        st.session_state
                                        .review_session_id
                                    ),
                                    message=(
                                        review_instruction
                                    ),
                                    approval_mode=(
                                        "ask_every_time"
                                    ),
                                )
                            )

                            job_id = started.get(
                                "job_id"
                            )

                            if not job_id:
                                raise RuntimeError(
                                    "SuperDocs did not "
                                    "return a job_id."
                                )

                            st.session_state.review_job_id = (
                                job_id
                            )

                            job = (
                                wait_until_action_needed(
                                    client=client,
                                    job_id=job_id,
                                )
                            )

                        status = job.get(
                            "status"
                        )

                        st.session_state.review_status = (
                            status
                        )

                        if status == "awaiting_approval":
                            metadata = (
                                job.get("metadata")
                                or {}
                            )

                            awaiting_kind = (
                                metadata.get(
                                    "awaiting_kind"
                                )
                            )

                            if (
                                awaiting_kind
                                == "continue_prompt"
                            ):
                                st.error(
                                    "SuperDocs requested "
                                    "continuation for a "
                                    "large operation. "
                                    "This demo expects a "
                                    "small surgical edit."
                                )

                            else:
                                changes = (
                                    parse_pending_changes(
                                        metadata.get(
                                            "pending_changes"
                                        )
                                    )
                                )

                                if not changes:
                                    raise RuntimeError(
                                        "SuperDocs is awaiting "
                                        "approval but returned "
                                        "no proposed changes."
                                    )

                                st.session_state.pending_changes = (
                                    changes
                                )

                        st.rerun()

                    except Exception as exc:
                        st.error(
                            str(exc)
                        )

            # ==============================================
            # DISPLAY DIFF
            # ==============================================

            if st.session_state.pending_changes:
                st.markdown(
                    "### Proposed changes"
                )

                st.warning(
                    "Inspect the proposed changes before "
                    "approving. Objections and responses "
                    "must remain untouched."
                )

                for index, change in enumerate(
                    st.session_state.pending_changes,
                    start=1,
                ):
                    with st.container(
                        border=True
                    ):
                        st.markdown(
                            f"**Change {index}**"
                        )

                        st.write(
                            "Operation:",
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
                                explanation
                            )

                        col_before, col_after = (
                            st.columns(2)
                        )

                        with col_before:
                            st.markdown(
                                "**Before**"
                            )

                            st.code(
                                change.get(
                                    "old_html",
                                    "(none)",
                                ),
                                language="html",
                            )

                        with col_after:
                            st.markdown(
                                "**After**"
                            )

                            st.code(
                                change.get(
                                    "new_html",
                                    "(none)",
                                ),
                                language="html",
                            )

                approve_col, reject_col = (
                    st.columns(2)
                )

                # ------------------------------------------
                # APPROVE
                # ------------------------------------------

                if approve_col.button(
                    "Approve all changes",
                    type="primary",
                ):
                    try:
                        client = SuperDocsClient()

                        decisions = [
                            {
                                "change_id":
                                    change["change_id"],
                                "approved": True,
                            }
                            for change in (
                                st.session_state
                                .pending_changes
                            )
                        ]

                        client.approve_changes(
                            session_id=(
                                st.session_state
                                .review_session_id
                            ),
                            job_id=(
                                st.session_state
                                .review_job_id
                            ),
                            approved=True,
                            changes=decisions,
                        )

                        with st.spinner(
                            "Applying approved change..."
                        ):
                            job = (
                                wait_until_action_needed(
                                    client=client,
                                    job_id=(
                                        st.session_state
                                        .review_job_id
                                    ),
                                )
                            )

                        st.session_state.review_status = (
                            job.get("status")
                        )

                        st.session_state.review_decision = (
                            "approved"
                        )

                        st.session_state.pending_changes = []

                        st.rerun()

                    except Exception as exc:
                        st.error(
                            str(exc)
                        )

                # ------------------------------------------
                # REJECT
                # ------------------------------------------

                if reject_col.button(
                    "Reject all changes"
                ):
                    try:
                        client = SuperDocsClient()

                        decisions = [
                            {
                                "change_id":
                                    change["change_id"],
                                "approved": False,
                            }
                            for change in (
                                st.session_state
                                .pending_changes
                            )
                        ]

                        client.approve_changes(
                            session_id=(
                                st.session_state
                                .review_session_id
                            ),
                            job_id=(
                                st.session_state
                                .review_job_id
                            ),
                            approved=False,
                            changes=decisions,
                        )

                        with st.spinner(
                            "Submitting rejection..."
                        ):
                            job = (
                                wait_until_action_needed(
                                    client=client,
                                    job_id=(
                                        st.session_state
                                        .review_job_id
                                    ),
                                )
                            )

                        st.session_state.review_status = (
                            job.get("status")
                        )

                        st.session_state.review_decision = (
                            "rejected"
                        )

                        st.session_state.pending_changes = []

                        st.rerun()

                    except Exception as exc:
                        st.error(
                            str(exc)
                        )

            if (
                st.session_state.review_status
                == "completed"
            ):
                if (
                    st.session_state.review_decision
                    == "approved"
                ):
                    st.success(
                        "Review completed — "
                        "human-approved changes applied."
                    )

                elif (
                    st.session_state.review_decision
                    == "rejected"
                ):
                    st.info(
                        "Review completed — "
                        "proposed changes rejected."
                    )

# ==========================================================
# TAB 4
# ==========================================================

with tab_export:
    result = st.session_state.parse_result
    coverage = st.session_state.coverage

    if result is None:
        st.info(
            "Process a source document first."
        )

    elif not coverage["coverage_passed"]:
        st.error(
            "Coverage validation failed. "
            "Export is blocked."
        )

    else:
        st.subheader(
            "Export cheatsheet"
        )

        st.caption(
            "Local exports preserve the deterministic "
            "lossless transformation."
        )

        markdown_bytes = (
            build_cheatsheet_markdown(
                result
            ).encode("utf-8")
        )

        docx_bytes = (
            build_cheatsheet_docx_bytes(
                result
            )
        )

        col1, col2 = st.columns(2)

        col1.download_button(
            "Download Markdown",
            data=markdown_bytes,
            file_name="objection_handling_cheatsheet.md",
            mime="text/markdown",
            key="export_tab_markdown_download",
        )

        col2.download_button(
            "Download generated DOCX",
            data=docx_bytes,
            file_name="objection_handling_cheatsheet.docx",
            mime=(
                "application/vnd.openxmlformats-"
                "officedocument.wordprocessingml.document"
            ),
            key="export_tab_docx_download",
        )

        st.divider()

        st.subheader(
            "Reviewed SuperDocs export"
        )

        if (
            st.session_state.review_decision
            != "approved"
            or st.session_state.review_status
            != "completed"
        ):
            st.info(
                "Approve a proposed SuperDocs edit "
                "in the Chat & Review tab to enable "
                "the reviewed export."
            )

        else:
            if (
                st.session_state.reviewed_docx_bytes
                is None
            ):
                if st.button(
                    "Export reviewed DOCX from SuperDocs",
                    type="primary",
                ):
                    try:
                        client = SuperDocsClient()

                        output_path = Path(
                            "outputs/"
                            "ui_reviewed_objection_"
                            "cheatsheet.docx"
                        )

                        with st.spinner(
                            "Exporting reviewed document..."
                        ):
                            exported = (
                                client.export_document(
                                    session_id=(
                                        st.session_state
                                        .review_session_id
                                    ),
                                    output_path=(
                                        output_path
                                    ),
                                    filename=(
                                        "sales_objection_"
                                        "handling_cheatsheet"
                                    ),
                                    file_format="docx",
                                )
                            )

                        st.session_state.reviewed_docx_bytes = (
                            exported.read_bytes()
                        )

                        st.success(
                            "Reviewed export ready."
                        )

                        st.rerun()

                    except Exception as exc:
                        st.error(
                            str(exc)
                        )

            if (
                st.session_state.reviewed_docx_bytes
                is not None
            ):
                st.download_button(
                    "Download reviewed SuperDocs DOCX",
                    data=st.session_state.reviewed_docx_bytes,
                    file_name="sales_objection_handling_cheatsheet.docx",
                    mime=(
                        "application/vnd."
                        "openxmlformats-officedocument."
                        "wordprocessingml.document"
                    ),
                    type="primary",
                    key="export_tab_reviewed_docx_download",
                )