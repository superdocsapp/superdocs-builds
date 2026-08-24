"""
Runs the Client Progress & Re-Assessment Report across a whole coaching
roster.

Per client, per run:

    1. Skip if this exact assessment was already committed.
    2. Make sure the client's SuperDocs document exists.
       - If the session has no document yet, create the baseline plan first.
    3. If there is only one assessment, stop after creating the baseline.
    4. Otherwise:
         - render the trend chart
         - upload the chart
         - build deterministic comparison-table HTML
         - persist the deterministic content
         - ask the AI for narrative sections
         - export the completed document

The important design rule is:

    deterministic numbers -> Python -> document

    narrative prose -> AI

Baseline values are explicitly supplied to the baseline AI instruction.
This prevents the "Please fill: weight" / "Please fill: body fat %"
placeholders caused by withholding the actual assessment values.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from .charts import render_trend_chart_png
from .models import Client
from .report_builder import (
    build_baseline_instruction,
    build_narrative_instruction,
    build_report_section_html,
)
from .state_store import StateStore
from .superdocs_client import retry_with_backoff


log = logging.getLogger("batch_runner")


class SuperDocsClientProtocol(Protocol):
    """
    The subset of SuperDocsClient used by this module.

    A Protocol allows the test suite to inject FakeSuperDocsClient
    without requiring network access or an API key.
    """

    def chat(
        self,
        message: str,
        session_id: str,
        document_html=None,
        approval_mode: str = "approve_all",
        model_tier=None,
    ):
        ...

    def list_session_documents(
        self,
        session_id: str,
    ) -> list[dict]:
        ...

    def persist_document(
        self,
        session_id: str,
        document_id: str,
        html: str,
    ) -> dict:
        ...

    def upload_image(
        self,
        png_bytes: bytes,
        filename: str = "chart.png",
    ) -> str:
        ...

    def export(
        self,
        *,
        session_id=None,
        html=None,
        fmt: str = "docx",
        filename=None,
    ) -> bytes:
        ...


@dataclass
class ClientRunResult:
    client_id: str
    status: str

    # Possible statuses:
    #
    # "baseline_created"
    # "report_appended"
    # "skipped_already_run"
    # "error"

    detail: str = ""
    export_path: Optional[str] = None


def _document_id(
    documents: list[dict],
) -> str:
    """
    Extract the durable document id from the API response.
    """

    if not documents:
        raise RuntimeError(
            "Cannot extract document id "
            "from an empty document list."
        )

    document = documents[0]

    document_id = (
        document.get("durable_document_id")
        or document.get("document_id")
        or document.get("id")
    )

    if not document_id:
        raise RuntimeError(
            "SuperDocs returned a document "
            "but no usable document id was found."
        )

    return document_id


def _ensure_baseline_document(
    client: Client,
    sd: SuperDocsClientProtocol,
    session_id: str,
) -> tuple[list[dict], Optional[str]]:
    """
    Ensure that the client's SuperDocs session has a document.

    Returns:

        (documents, baseline_version_id)

    baseline_version_id is:
        - the version returned by the baseline chat if we created it
        - None if the document already existed
    """

    # ---------------------------------------------------------------
    # First check whether a document already exists.
    # ---------------------------------------------------------------

    documents = retry_with_backoff(
        lambda: sd.list_session_documents(
            session_id
        )
    )

    if documents:
        return documents, None

    # ---------------------------------------------------------------
    # No document exists.
    #
    # Create the initial plan.
    #
    # IMPORTANT:
    # build_baseline_instruction() contains the actual baseline
    # measurements. Previously this prompt only said "use the
    # client's baseline assessment" without supplying the values.
    # ---------------------------------------------------------------

    result = sd.chat(
        message=build_baseline_instruction(
            client
        ),
        session_id=session_id,
        document_html="",
        approval_mode="approve_all",
    )

    # ---------------------------------------------------------------
    # The chat call should have created a document.
    # ---------------------------------------------------------------

    documents = retry_with_backoff(
        lambda: sd.list_session_documents(
            session_id
        )
    )

    if not documents:
        raise RuntimeError(
            f"{client.client_id}: baseline chat completed "
            f"but session {session_id} still has no document. "
            "Check the SuperDocs document-list response."
        )

    log.info(
        "%s -> baseline document created",
        client.client_id,
    )

    return documents, result.version_id


def process_client(
    client: Client,
    sd: SuperDocsClientProtocol,
    state: StateStore,
    output_dir: Path,
) -> ClientRunResult:
    """
    Process the latest assessment for one client.

    The latest assessment index is used as the idempotency key.
    """

    if not client.assessments:
        raise ValueError(
            f"{client.client_id}: client has no assessments."
        )

    assessment_index = (
        len(client.assessments) - 1
    )

    session_id = (
        state.session_id_for(
            client.client_id
        )
    )

    # ---------------------------------------------------------------
    # 1. Idempotency
    # ---------------------------------------------------------------

    if state.already_processed(
        client.client_id,
        assessment_index,
    ):
        return ClientRunResult(
            client.client_id,
            "skipped_already_run",
            (
                f"assessment {assessment_index} "
                "already committed"
            ),
        )

    # ---------------------------------------------------------------
    # 2. Make sure the document exists
    # ---------------------------------------------------------------

    documents, baseline_version_id = (
        _ensure_baseline_document(
            client=client,
            sd=sd,
            session_id=session_id,
        )
    )

    # ---------------------------------------------------------------
    # 3. Baseline-only client
    # ---------------------------------------------------------------

    if not client.is_reassessment():

        state.mark_run(
            client.client_id,
            assessment_index=assessment_index,
            version_id=baseline_version_id,
            export_path=None,
        )

        return ClientRunResult(
            client.client_id,
            "baseline_created",
            (
                "initial plan document drafted; "
                "no comparison yet"
            ),
        )

    # ---------------------------------------------------------------
    # 4. Reassessment
    # ---------------------------------------------------------------

    # ---------------------------------------------------------------
    # A) Render deterministic chart.
    # ---------------------------------------------------------------

    png = render_trend_chart_png(client)

    # ---------------------------------------------------------------
    # B) Upload chart.
    # ---------------------------------------------------------------

    chart_url = retry_with_backoff(
        lambda: sd.upload_image(
            png,
            filename=(
                f"{client.client_id}-trend.png"
            ),
        )
    )

    # ---------------------------------------------------------------
    # C) Build deterministic comparison table + chart HTML.
    # ---------------------------------------------------------------

    section_html = build_report_section_html(
        client,
        chart_url,
    )

    # ---------------------------------------------------------------
    # D) Get the existing durable document id.
    # ---------------------------------------------------------------

    document_id = _document_id(
        documents
    )

    # ---------------------------------------------------------------
    # E) Persist deterministic content.
    #
    # IMPORTANT:
    # This is intentionally NOT sent through AI.
    # ---------------------------------------------------------------

    sd.persist_document(
        session_id=session_id,
        document_id=document_id,
        html=section_html,
    )

    # ---------------------------------------------------------------
    # F) Ask AI for narrative only.
    #
    # Do not retry this automatically.
    # A timeout after server-side processing could otherwise create
    # duplicate narrative turns.
    # ---------------------------------------------------------------

    narrative_result = sd.chat(
        message=build_narrative_instruction(
            client
        ),
        session_id=session_id,
        approval_mode="approve_all",
    )

    # ---------------------------------------------------------------
    # G) Export final document.
    # ---------------------------------------------------------------

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    docx_bytes = retry_with_backoff(
        lambda: sd.export(
            session_id=session_id,
            fmt="docx",
            filename=(
                f"{client.client_id}"
                "-progress-report"
            ),
        )
    )

    export_path = (
        output_dir
        / (
            f"{client.client_id}"
            "-progress-report.docx"
        )
    )

    export_path.write_bytes(
        docx_bytes
    )

    # ---------------------------------------------------------------
    # 5. Commit state only after successful export.
    # ---------------------------------------------------------------

    state.mark_run(
        client.client_id,
        assessment_index=assessment_index,
        version_id=narrative_result.version_id,
        export_path=str(export_path),
    )

    return ClientRunResult(
        client.client_id,
        "report_appended",
        (
            "chart + deterministic table persisted, "
            "narrative added, exported to "
            f"{export_path}"
        ),
        export_path=str(export_path),
    )


def run_batch(
    clients: list[Client],
    sd: SuperDocsClientProtocol,
    state: StateStore,
    output_dir: Path,
    limit: Optional[int] = None,
) -> list[ClientRunResult]:
    """
    Process a roster.

    --limit is intentionally handled here so the same function
    can be used by both the CLI and tests.
    """

    results: list[ClientRunResult] = []

    roster = (
        clients[:limit]
        if limit
        else clients
    )

    for client in roster:

        try:
            result = process_client(
                client,
                sd,
                state,
                output_dir,
            )

        except Exception as exc:
            log.exception(
                "Failed processing %s",
                client.client_id,
            )

            result = ClientRunResult(
                client.client_id,
                "error",
                str(exc),
            )

        results.append(result)

        log.info(
            "%s -> %s (%s)",
            client.client_id,
            result.status,
            result.detail,
        )

    return results