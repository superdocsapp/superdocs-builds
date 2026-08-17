import pytest
import hashlib
from uuid import UUID
from core.models import (
    Run,
    Document,
    Chunk,
    ChangeFact,
    Finding,
    ReviewDecision,
    TraceRecord,
    Job,
)

RID = UUID("00000000-0000-0000-0000-000000000001")


class TestModels:
    def test_run_defaults(self):
        run = Run(trigger="manual")
        assert run.status == "pending"
        assert run.id is not None

    def test_document_required_fields(self):
        rid = UUID("00000000-0000-0000-0000-000000000001")
        doc = Document(
            run_id=rid,
            session_id="sess-1",
            filename="test.md",
            file_hash="abc123",
        )
        assert doc.filename == "test.md"
        assert doc.run_id == rid

    def test_finding_state_literal(self):
        finding = Finding(
            run_id=RID,
            state="CONFIRMED_DRIFT",
            evidence_quote="npm install",
            evidence_chunk_id="chunk-001",
        )
        assert finding.state == "CONFIRMED_DRIFT"

    def test_finding_no_evidence_for_unknown(self):
        finding = Finding(
            run_id=RID,
            state="UNKNOWN",
        )
        assert finding.state == "UNKNOWN"
        assert finding.evidence_quote is None

    def test_change_fact_types(self):
        cf = ChangeFact(
            run_id=RID,
            type="renamed",
            old_value="npm",
            new_value="pnpm",
            source_ref="CHANGELOG.md",
        )
        assert cf.type == "renamed"

    def test_review_decision_required(self):
        rd = ReviewDecision(
            finding_id=RID,
            decision="approved",
        )
        assert rd.decision == "approved"

    def test_trace_record_default_ops_zero(self):
        tr = TraceRecord(
            run_id=RID,
            node="FINDER",
            input_hash="abc",
        )
        assert tr.superdocs_ops == 0

    def test_job_defaults(self):
        job = Job(kind="ingestion", agent="agent_1")
        assert job.kind == "ingestion"
        assert job.status == "pending"