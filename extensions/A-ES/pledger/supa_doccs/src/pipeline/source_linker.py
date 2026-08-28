"""Source linker for attaching and resolving source pointers.

Attaches provenance pointers to extracted facts and resolves them
back to the original text substring.
"""

import re
import uuid
from decimal import Decimal
from typing import Any, Callable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from src.models.claims import Claim, SourceLocation
from src.pipeline.extractors.base import ExtractedFact, SourceSpan


class SourceResolutionError(Exception):
    """Raised when a source pointer cannot be resolved."""

    def __init__(self, claim_id: str, source_location_id: str, reason: str):
        self.claim_id = claim_id
        self.source_location_id = source_location_id
        self.reason = reason
        super().__init__(f"Cannot resolve source for claim {claim_id}: {reason}")


class SourceLinker:
    """Attaches and resolves source pointers for extracted facts."""

    def attach(
        self,
        fact: ExtractedFact,
        document_version_id: str,
    ) -> SourceLocation:
        """Create a SourceLocation record from an ExtractedFact's span.

        Validates: source_span is not None, and start_offset < end_offset.

        Args:
            fact: The extracted fact containing source span information.
            document_version_id: UUID string of the document version.

        Returns:
            A SourceLocation model instance (not yet persisted).

        Raises:
            ValueError: If source_span is None or start_offset >= end_offset.
        """
        if fact.source_span is None:
            raise ValueError(
                f"Cannot attach source pointer: source_span is None "
                f"(citation unverifiable for field '{fact.field_name}')"
            )

        start = fact.source_span.start_offset
        end = fact.source_span.end_offset

        if start >= end:
            raise ValueError(
                f"start_offset ({start}) must be strictly less than end_offset ({end})"
            )

        source_location = SourceLocation(
            document_version_id=uuid.UUID(document_version_id),
            page_number=fact.source_span.page_number,
            section_id=fact.source_span.section_id,
            start_offset=start,
            end_offset=end,
            clause_ref=fact.fact_group_id,
        )

        return source_location

    def resolve(
        self,
        source_location: SourceLocation,
        stored_text: str,
    ) -> str:
        """Resolve a source pointer to the original substring.

        Returns text[start_offset:end_offset].

        Args:
            source_location: The SourceLocation to resolve.
            stored_text: The full text of the document page/section.

        Returns:
            The substring from start_offset to end_offset.

        Raises:
            SourceResolutionError: If offsets exceed text length or
                document_version_id doesn't exist.
        """
        claim_id = str(source_location.claim_id) if source_location.claim_id else ""
        source_location_id = str(source_location.id) if source_location.id else ""

        if source_location.document_version_id is None:
            raise SourceResolutionError(
                claim_id=claim_id,
                source_location_id=source_location_id,
                reason="missing document_version_id",
            )

        text_length = len(stored_text)
        start = source_location.start_offset
        end = source_location.end_offset

        if end > text_length or start > text_length:
            raise SourceResolutionError(
                claim_id=claim_id,
                source_location_id=source_location_id,
                reason=(
                    f"offsets ({start}:{end}) exceed document text length ({text_length})"
                ),
            )

        return stored_text[start:end]


# Regex to detect repayment row fact_group_id pattern like "row_1", "row_23"
_ROW_PATTERN = re.compile(r"^row_(\d+)$")


def persist_fact(
    fact: ExtractedFact,
    document_version_id: str,
    run_id: str,
    document_type: str,
    session: Session,
    extraction_method: Optional[str] = None,
) -> tuple[Claim, Optional[SourceLocation]]:
    """Persist an ExtractedFact as a Claim + optional SourceLocation pair.

    Maps ExtractedFact → Claim record using compound claim_type format.
    For repayment statements with row indexing (fact_group_id like "row_N"),
    the claim_type becomes `repayment_statement.row_N.field_name`.
    For other document types, claim_type is `{document_type}.{field_name}`.

    If source_span is None (unverifiable citation), the Claim is persisted
    but no SourceLocation is created.

    Args:
        fact: The extracted fact to persist.
        document_version_id: UUID string of the document version.
        run_id: UUID string of the pipeline run.
        document_type: Classification label (e.g. "loan_agreement").
        session: SQLAlchemy session for persistence.
        extraction_method: How the fact was extracted
            ('structured' | 'llm' | 'llm_fallback' | 'regex_fallback').

    Returns:
        Tuple of (Claim, SourceLocation or None) that were added to the session.
    """
    # Build claim_type with repayment row indexing support
    if fact.fact_group_id and _ROW_PATTERN.match(fact.fact_group_id):
        # e.g. repayment_statement.row_1.amount_paid
        claim_type = f"{document_type}.{fact.fact_group_id}.{fact.field_name}"
    else:
        # e.g. loan_agreement.borrower_name
        claim_type = f"{document_type}.{fact.field_name}"

    claim = Claim(
        document_version_id=uuid.UUID(document_version_id),
        run_id=uuid.UUID(run_id),
        extracted_text=fact.value,
        claim_type=claim_type,
        confidence=Decimal(str(round(fact.confidence, 3))),
        field_name=fact.field_name[:128],
        extraction_method=extraction_method[:16] if extraction_method else None,
    )
    session.add(claim)
    session.flush()  # get claim.id

    # Only create SourceLocation if source_span is verifiable
    if fact.source_span is None:
        return claim, None

    source_location = SourceLocation(
        claim_id=claim.id,
        document_version_id=uuid.UUID(document_version_id),
        page_number=fact.source_span.page_number,
        section_id=fact.source_span.section_id,
        start_offset=fact.source_span.start_offset,
        end_offset=fact.source_span.end_offset,
        clause_ref=fact.fact_group_id,
    )
    session.add(source_location)
    return claim, source_location


# ---------------------------------------------------------------------------
# Node-completion persistence for extract_claims
#
# persist_fact() above was dead code: the extract_claims node built
# SourceLocation objects via SourceLinker.attach() and discarded them,
# leaving claims/source_locations unwritten (data lived only in the
# PipelineState JSONB checkpoint). The functions below make the
# extraction node write the durable record at NODE COMPLETION — not at
# some later finalize step that may never run. The JSONB checkpoint is
# kept untouched as the resumability mechanism; both stores end up
# holding equivalent data.
# ---------------------------------------------------------------------------


_TRAILING_INDEX_RE = re.compile(r"[-_]\d+$")


def _result_to_fact(
    result: dict[str, Any], document_type: str
) -> Optional[ExtractedFact]:
    """Map an ExtractionResult dict onto an ExtractedFact for persist_fact().

    Derives field_name from the claim_id ("doc_type.field_N" → "field",
    "doc-001" → "001"). Grounded results with a valid span get a
    SourceSpan; anything unverifiable or degenerate (start >= end)
    maps to source_span=None, which persist_fact treats as an
    unverifiable citation.
    """
    claim_id = str(result.get("claim_id", ""))
    if not claim_id:
        return None

    field_name = claim_id
    prefix = f"{document_type}."
    if field_name.startswith(prefix):
        field_name = field_name[len(prefix):]
    elif field_name.startswith(document_type):
        field_name = field_name[len(document_type):]
    field_name = _TRAILING_INDEX_RE.sub("", field_name) or claim_id

    try:
        confidence = min(1.0, max(0.0, float(result.get("confidence", 0.7))))
    except (TypeError, ValueError):
        confidence = 0.7

    source_span: Optional[SourceSpan] = None
    if result.get("citation_status") == "grounded":
        try:
            start = int(result.get("start_offset", 0))
            end = int(result.get("end_offset", 0))
        except (TypeError, ValueError):
            start, end = 0, 0
        if 0 <= start < end:
            source_span = SourceSpan(
                start_offset=start,
                end_offset=end,
                page_number=result.get("page_number"),
                section_id=result.get("section_id"),
            )

    return ExtractedFact(
        field_name=field_name,
        value=str(result.get("claim_text", "")),
        confidence=confidence,
        source_span=source_span,
    )


def persist_extraction_results(
    session_factory: sessionmaker,
    state: dict[str, Any],
    claims: list[dict[str, Any]],
) -> int:
    """Persist a run's extracted claims to claims/source_locations NOW.

    Called by the extract_claims node on completion. Idempotent per run:
    existing rows for the run are replaced so resumed/retried runs never
    duplicate. Uses persist_fact() as the single mapping path.

    Returns:
        Number of claims persisted.
    """
    run_id = str(state.get("run_id", ""))
    document_version_id = str(state.get("document_version_id", ""))
    document_type = str(state.get("classification_label") or "unknown")

    if not run_id or not document_version_id:
        raise ValueError(
            "persist_extraction_results requires run_id and "
            "document_version_id in state"
        )
    run_uuid = uuid.UUID(run_id)

    with session_factory() as session:  # type: Session
        # Replace-any: delete this run's previous rows first so retries
        # and resume-from-checkpoint don't duplicate the durable record.
        session.execute(
            text(
                """
                DELETE FROM source_locations
                WHERE claim_id IN (
                    SELECT id FROM claims WHERE run_id = :run_id
                )
                """
            ),
            {"run_id": run_uuid},
        )
        session.execute(
            text("DELETE FROM claims WHERE run_id = :run_id"),
            {"run_id": run_uuid},
        )

        persisted = 0
        for result in claims:
            fact = _result_to_fact(dict(result), document_type)
            if fact is None:
                continue
            persist_fact(
                fact=fact,
                document_version_id=document_version_id,
                run_id=run_id,
                document_type=document_type,
                session=session,
                extraction_method=result.get("_extraction_method"),
            )
            persisted += 1

        session.commit()
        return persisted


def make_sql_claim_persister(
    session_factory: sessionmaker,
) -> Callable[[dict[str, Any], list[dict[str, Any]]], int]:
    """Build the persister callable injected into the extract_claims node."""

    def _persist(state: dict[str, Any], claims: list[dict[str, Any]]) -> int:
        return persist_extraction_results(session_factory, state, claims)

    return _persist
