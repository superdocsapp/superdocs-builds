from __future__ import annotations

import tempfile
import time
from pathlib import Path
from uuid import uuid4

import streamlit as st

from core.rewriter import propose_rewrite
from superdocs.client import (
    SuperDocsClient,
    SuperDocsError,
)
from superdocs.parser import (
    SuperDocsParseError,
    pending_changes_from_job,
)
from superdocs.polling import (
    wait_until_action_needed,
)


st.set_page_config(
    page_title="Evidence-First Resume Bullet Rewriter",
    page_icon="📝",
    layout="wide",
)


# ==========================================================
# STATE
# ==========================================================


def initialize_state() -> None:
    defaults = {
        "proposal": None,
        "source_bullet": None,
        "requested_claim": "",
        "resume_session_id": None,
        "resume_document_id": None,
        "resume_filename": None,
        "review_job_id": None,
        "pending_changes": [],
        "review_status": None,
        "review_decision": None,
        "reviewed_docx_bytes": None,
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_review_state() -> None:
    st.session_state.review_job_id = None
    st.session_state.pending_changes = []
    st.session_state.review_status = None
    st.session_state.review_decision = None
    st.session_state.reviewed_docx_bytes = None


initialize_state()


# ==========================================================
# SUPERDOCS HELPERS
# ==========================================================


def upload_resume_to_superdocs(
    uploaded_file,
) -> None:
    suffix = (
        Path(uploaded_file.name).suffix
        or ".docx"
    )

    temp_path: Path | None = None

    try:
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

        client = SuperDocsClient()

        requested_session_id = (
            "resume-bullet-"
            + uuid4().hex[:10]
        )

        upload = client.upload_document(
            path=temp_path,
            session_id=requested_session_id,
            open_mode="replace",
        )

        st.session_state.resume_session_id = (
            upload.get("session_id")
            or requested_session_id
        )

        st.session_state.resume_document_id = (
            upload.get("document_id")
        )

        st.session_state.resume_filename = (
            uploaded_file.name
        )

        reset_review_state()

    finally:
        if temp_path is not None:
            temp_path.unlink(
                missing_ok=True
            )


def wait_until_completed(
    *,
    client: SuperDocsClient,
    job_id: str,
    timeout_seconds: int = 180,
    poll_interval: float = 2.0,
) -> dict:
    """
    Used after the human approval decision.

    Unlike wait_until_action_needed(), this keeps
    polling past awaiting_approval until the job
    actually completes.
    """

    started = time.monotonic()

    while True:
        job = client.get_job(
            job_id=job_id
        )

        status = job.get("status")

        if status == "completed":
            return job

        if status == "failed":
            raise SuperDocsError(
                job.get(
                    "error",
                    "SuperDocs job failed.",
                )
            )

        if status == "cancelled":
            raise SuperDocsError(
                "SuperDocs job was cancelled."
            )

        elapsed = (
            time.monotonic()
            - started
        )

        if elapsed >= timeout_seconds:
            raise TimeoutError(
                f"Job {job_id} did not complete "
                f"within {timeout_seconds} seconds."
            )

        time.sleep(
            poll_interval
        )


def build_review_instruction(
    original: str,
    proposed: str,
) -> str:
    return f"""
Replace exactly this resume bullet:

SOURCE BULLET:
{original}

REPLACEMENT BULLET:
{proposed}

Rules:
- Change only the source bullet shown above.
- Use the replacement wording exactly as supplied.
- Do not modify any other resume content.
- Do not add new metrics.
- Do not change existing metrics.
- Do not invent responsibilities.
- Do not invent leadership experience.
- Do not invent technologies.
- Do not make any other edits.
- If the exact source bullet cannot be found, do not substitute a different bullet.
""".strip()


def export_reviewed_resume() -> bytes:
    session_id = (
        st.session_state.resume_session_id
    )

    if not session_id:
        raise RuntimeError(
            "No SuperDocs resume session exists."
        )

    source_name = (
        st.session_state.resume_filename
        or "resume.docx"
    )

    output_name = (
        Path(source_name).stem
        + "_reviewed.docx"
    )

    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".docx",
        ) as temp_file:
            temp_path = Path(
                temp_file.name
            )

        client = SuperDocsClient()

        client.export_document(
            session_id=session_id,
            output_path=temp_path,
            filename=output_name,
            file_format="docx",
        )

        return temp_path.read_bytes()

    finally:
        if temp_path is not None:
            temp_path.unlink(
                missing_ok=True
            )


# ==========================================================
# HEADER
# ==========================================================


st.title(
    "Evidence-First Resume Bullet Rewriter"
)

st.caption(
    "Strengthen resume bullets without inventing "
    "metrics, experience, or responsibilities."
)

st.info(
    "This tool only uses evidence supplied in the "
    "resume or by the user. If measurable impact "
    "is missing, it asks instead of guessing."
)


# ==========================================================
# 1. SOURCE BULLET
# ==========================================================


st.subheader(
    "1. Source bullet"
)

source_bullet = st.text_area(
    "Paste one resume bullet",
    value=(
        "Automated invoice processing "
        "using Python."
    ),
    height=100,
)


# ==========================================================
# 2. OPTIONAL REQUEST
# ==========================================================


st.subheader(
    "2. Optional instruction"
)

requested_claim = st.text_input(
    "Anything specific you want emphasized?",
    placeholder=(
        "Example: Emphasize my "
        "leadership experience"
    ),
)


if st.button(
    "Analyse bullet",
    type="primary",
    use_container_width=True,
):
    proposal = propose_rewrite(
        source_bullet,
        requested_claim=(
            requested_claim
            or None
        ),
    )

    st.session_state.proposal = (
        proposal
    )

    st.session_state.source_bullet = (
        source_bullet
    )

    st.session_state.requested_claim = (
        requested_claim
    )

    reset_review_state()


proposal = (
    st.session_state.proposal
)


# ==========================================================
# 3. EVIDENCE CHECK
# ==========================================================


if proposal:
    st.divider()

    st.subheader(
        "3. Evidence check"
    )

    left, right = st.columns(2)

    with left:
        st.markdown(
            "**Source bullet**"
        )

        st.write(
            proposal.original_bullet
        )

    with right:
        st.markdown(
            "**Status**"
        )

        if proposal.status == "ready":
            st.success(
                "Ready for review"
            )

        elif (
            proposal.status
            == "needs_metric"
        ):
            st.warning(
                "More evidence needed"
            )

        else:
            st.error(
                "Unsupported request"
            )

    if proposal.evidence_used:
        st.markdown(
            "**Evidence found**"
        )

        for evidence in (
            proposal.evidence_used
        ):
            st.code(
                evidence
            )

    else:
        st.caption(
            "No explicit quantitative "
            "evidence found."
        )


    # ======================================================
    # MISSING METRIC
    # ======================================================

    if (
        proposal.status
        == "needs_metric"
    ):
        st.markdown(
            "### Missing evidence"
        )

        st.write(
            proposal.reason
        )

        for question in (
            proposal.questions
        ):
            st.info(
                question
            )

        supplied_metric = st.text_input(
            "Add measurable evidence "
            "you actually know",
            placeholder=(
                "Example: Reduced processing "
                "time from 3 hours to "
                "45 minutes"
            ),
            key="supplied_metric",
        )

        if st.button(
            "Use this evidence",
            use_container_width=True,
        ):
            updated = propose_rewrite(
                st.session_state[
                    "source_bullet"
                ],
                supplied_metric=(
                    supplied_metric
                ),
                requested_claim=(
                    st.session_state[
                        "requested_claim"
                    ]
                    or None
                ),
            )

            st.session_state.proposal = (
                updated
            )

            reset_review_state()

            st.rerun()


    # ======================================================
    # UNSUPPORTED REQUEST
    # ======================================================

    elif (
        proposal.status
        == "unsupported"
    ):
        st.error(
            proposal.reason
        )

        st.markdown(
            """
The requested claim was **not added**
because it could not be supported by
the supplied resume evidence.
"""
        )


    # ======================================================
    # READY
    # ======================================================

    elif (
        proposal.status
        == "ready"
    ):
        st.subheader(
            "4. Proposed rewrite"
        )

        before, after = (
            st.columns(2)
        )

        with before:
            st.markdown(
                "**Before**"
            )

            st.text_area(
                "Original",
                proposal.original_bullet,
                height=120,
                disabled=True,
                label_visibility="collapsed",
                key="before_text",
            )

        with after:
            st.markdown(
                "**After**"
            )

            st.text_area(
                "Proposal",
                (
                    proposal.proposed_bullet
                    or ""
                ),
                height=120,
                disabled=True,
                label_visibility="collapsed",
                key="after_text",
            )

        st.success(
            "No unsupported metric or "
            "experience was introduced."
        )

        st.caption(
            proposal.reason
        )


        # ==================================================
        # 5. UPLOAD RESUME
        # ==================================================

        st.divider()

        st.subheader(
            "5. Open resume in SuperDocs"
        )

        st.write(
            "Upload the DOCX that contains "
            "the source bullet. The proposed "
            "rewrite will not be applied until "
            "you explicitly approve it."
        )

        uploaded_resume = (
            st.file_uploader(
                "Upload resume DOCX",
                type=["docx"],
                key="resume_uploader",
            )
        )

        if (
            uploaded_resume
            is not None
        ):
            st.caption(
                "Selected: "
                f"`{uploaded_resume.name}`"
            )

            if st.button(
                "Open resume in SuperDocs",
                type="primary",
                key="upload_resume_button",
            ):
                try:
                    with st.spinner(
                        "Uploading resume "
                        "to SuperDocs..."
                    ):
                        upload_resume_to_superdocs(
                            uploaded_resume
                        )

                    st.success(
                        "Resume opened "
                        "successfully."
                    )

                    st.rerun()

                except Exception as exc:
                    st.error(
                        str(exc)
                    )


        # ==================================================
        # 6. HUMAN REVIEW
        # ==================================================

        if (
            st.session_state
            .resume_session_id
        ):
            st.success(
                "Resume is ready "
                "in SuperDocs."
            )

            st.caption(
                "Document: "
                + str(
                    st.session_state
                    .resume_filename
                )
            )

            st.subheader(
                "6. SuperDocs human review"
            )

            review_instruction = (
                build_review_instruction(
                    proposal.original_bullet,
                    (
                        proposal
                        .proposed_bullet
                        or ""
                    ),
                )
            )

            with st.expander(
                "Exact edit instruction"
            ):
                st.code(
                    review_instruction
                )

            if (
                not st.session_state
                .pending_changes
                and st.session_state
                .review_status
                not in {
                    "completed",
                    "rejected",
                }
            ):
                button_label = (
                    "Resume SuperDocs Review"
                    if (
                        st.session_state.review_job_id
                        and st.session_state.review_status
                        == "awaiting_approval"
                    )
                    else "Start SuperDocs Review"
                )

                if st.button(
                    button_label,
                    type="primary",
                    key="start_review_button",
                ):
                    try:
                        client = SuperDocsClient()

                        existing_job_id = (
                            st.session_state
                            .review_job_id
                        )

                        with st.spinner(
                            "Loading the existing "
                            "SuperDocs review..."
                            if (
                                existing_job_id
                                and st.session_state
                                .review_status
                                == "awaiting_approval"
                            )
                            else (
                                "SuperDocs is preparing "
                                "the proposed edit..."
                            )
                        ):
                            if (
                                existing_job_id
                                and st.session_state
                                .review_status
                                == "awaiting_approval"
                            ):
                                # Graceful re-entry:
                                # reuse the already-created job instead
                                # of starting another review request.
                                job_id = existing_job_id
                                job = client.get_job(
                                    job_id=job_id
                                )

                            else:
                                started = (
                                    client.start_async_chat(
                                        session_id=(
                                            st.session_state
                                            .resume_session_id
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

                                st.session_state[
                                    "review_job_id"
                                ] = job_id

                                job = wait_until_action_needed(
                                    client=client,
                                    job_id=job_id,
                                    timeout_seconds=180,
                                )

                            status = job.get(
                                "status"
                            )

                            st.session_state[
                                "review_status"
                            ] = status

                            metadata = (
                                job.get("metadata")
                                or {}
                            )

                            if (
                                status
                                == "awaiting_approval"
                                and isinstance(
                                    metadata,
                                    dict,
                                )
                                and metadata.get(
                                    "awaiting_kind"
                                )
                                == "continue_prompt"
                            ):
                                raise RuntimeError(
                                    "SuperDocs requested "
                                    "continuation for a larger "
                                    "operation. This demo expects "
                                    "one small surgical edit."
                                )

                            changes = (
                                pending_changes_from_job(
                                    job
                                )
                            )

                            st.session_state[
                                "pending_changes"
                            ] = changes

                            if (
                                status
                                == "awaiting_approval"
                                and not changes
                            ):
                                raise RuntimeError(
                                    "SuperDocs reached "
                                    "awaiting_approval but "
                                    "returned no proposed changes."
                                )

                        st.rerun()

                    except (
                        SuperDocsError,
                        SuperDocsParseError,
                        TimeoutError,
                        RuntimeError,
                    ) as exc:
                        st.error(
                            str(exc)
                        )


            # ==============================================
            # SHOW PROPOSED CHANGES
            # ==============================================

            pending_changes = (
                st.session_state
                .pending_changes
            )

            if pending_changes:
                st.warning(
                    "SuperDocs has proposed "
                    "a change. Nothing has "
                    "been applied yet."
                )

                for index, change in enumerate(
                    pending_changes,
                    start=1,
                ):
                    with st.container(
                        border=True
                    ):
                        st.markdown(
                            f"### Proposed "
                            f"change {index}"
                        )

                        operation = (
                            change.get(
                                "operation"
                            )
                        )

                        explanation = (
                            change.get(
                                "ai_explanation"
                            )
                        )

                        if operation:
                            st.caption(
                                "Operation: "
                                + str(
                                    operation
                                )
                            )

                        if explanation:
                            st.write(
                                "**Explanation:** "
                                + str(
                                    explanation
                                )
                            )

                        before_html = (
                            change.get(
                                "old_html"
                            )
                            or change.get(
                                "before_html"
                            )
                            or change.get(
                                "before"
                            )
                            or ""
                        )

                        after_html = (
                            change.get(
                                "new_html"
                            )
                            or change.get(
                                "after_html"
                            )
                            or change.get(
                                "after"
                            )
                            or ""
                        )

                        left_change, right_change = (
                            st.columns(2)
                        )

                        with left_change:
                            st.markdown(
                                "**Before**"
                            )

                            st.code(
                                before_html
                                or "(empty)",
                                language="html",
                            )

                        with right_change:
                            st.markdown(
                                "**After**"
                            )

                            st.code(
                                after_html
                                or "(empty)",
                                language="html",
                            )

                approve_col, reject_col = (
                    st.columns(2)
                )

                with approve_col:
                    if st.button(
                        "Approve proposed change",
                        type="primary",
                        use_container_width=True,
                        key="approve_change",
                    ):
                        try:
                            client = (
                                SuperDocsClient()
                            )

                            with st.spinner(
                                "Applying approved "
                                "change..."
                            ):
                                decisions = [
                                    {
                                        "change_id": change["change_id"],
                                        "approved": True,
                                    }
                                    for change in pending_changes
                                ]

                                client.approve_changes(
                                    session_id=(
                                        st.session_state
                                        .resume_session_id
                                    ),
                                    job_id=(
                                        st.session_state
                                        .review_job_id
                                    ),
                                    changes=decisions,
                                    approved=True,
                                )

                                wait_until_completed(
                                    client=client,
                                    job_id=(
                                        st.session_state
                                        .review_job_id
                                    ),
                                    timeout_seconds=180,
                                )

                            st.session_state[
                                "pending_changes"
                            ] = []

                            st.session_state[
                                "review_status"
                            ] = "completed"

                            st.session_state[
                                "review_decision"
                            ] = "approved"

                            st.success(
                                "Change approved "
                                "and applied."
                            )

                            st.rerun()

                        except Exception as exc:
                            st.error(
                                str(exc)
                            )

                with reject_col:
                    if st.button(
                        "Reject proposed change",
                        use_container_width=True,
                        key="reject_change",
                    ):
                        try:
                            client = (
                                SuperDocsClient()
                            )

                            with st.spinner(
                                "Rejecting proposed "
                                "change..."
                            ):
                                decisions = [
                                    {
                                        "change_id": change["change_id"],
                                        "approved": False,
                                    }
                                    for change in pending_changes
                                ]

                                client.approve_changes(
                                    session_id=(
                                        st.session_state
                                        .resume_session_id
                                    ),
                                    job_id=(
                                        st.session_state
                                        .review_job_id
                                    ),
                                    changes=decisions,
                                    approved=False,
                                )

                            st.session_state[
                                "pending_changes"
                            ] = []

                            st.session_state[
                                "review_status"
                            ] = "rejected"

                            st.session_state[
                                "review_decision"
                            ] = "rejected"

                            st.rerun()

                        except Exception as exc:
                            st.error(
                                str(exc)
                            )


            # ==============================================
            # APPROVED
            # ==============================================

            if (
                st.session_state
                .review_decision
                == "approved"
            ):
                st.success(
                    "Human approval complete. "
                    "The reviewed document "
                    "can now be exported."
                )

                st.subheader(
                    "7. Export reviewed DOCX"
                )

                if st.button(
                    "Prepare reviewed DOCX",
                    type="primary",
                    key="prepare_export",
                ):
                    try:
                        with st.spinner(
                            "Exporting reviewed "
                            "resume..."
                        ):
                            (
                                st.session_state[
                                    "reviewed_docx_bytes"
                                ]
                            ) = (
                                export_reviewed_resume()
                            )

                        st.rerun()

                    except Exception as exc:
                        st.error(
                            str(exc)
                        )

                if (
                    st.session_state
                    .reviewed_docx_bytes
                ):
                    source_name = (
                        st.session_state
                        .resume_filename
                        or "resume.docx"
                    )

                    output_name = (
                        Path(source_name).stem
                        + "_reviewed.docx"
                    )

                    st.download_button(
                        "Download reviewed DOCX",
                        data=(
                            st.session_state
                            .reviewed_docx_bytes
                        ),
                        file_name=(
                            output_name
                        ),
                        mime=(
                            "application/vnd."
                            "openxmlformats-"
                            "officedocument."
                            "wordprocessingml."
                            "document"
                        ),
                        use_container_width=True,
                        key="download_reviewed_docx",
                    )


            # ==============================================
            # REJECTED
            # ==============================================

            elif (
                st.session_state
                .review_decision
                == "rejected"
            ):
                st.warning(
                    "The proposed change was "
                    "rejected. The resume was "
                    "not intentionally changed "
                    "by this review."
                )

                if st.button(
                    "Reset review",
                    key="reset_review",
                ):
                    reset_review_state()
                    st.rerun()