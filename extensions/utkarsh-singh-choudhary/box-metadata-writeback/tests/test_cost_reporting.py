from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.workflow.pipeline import BoxMetadataWritebackPipeline

CONTRACT_TEXT = b"""SERVICES AGREEMENT
Counterparty: Acme Logistics Inc
Effective Date: 2026-01-15
Value: $84,000
"""

CORRESPONDENCE_TEXT = b"Dear team, following up on the policy update."


def test_happy_path_reports_one_operation_per_chat_stage():
    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    pipeline = BoxMetadataWritebackPipeline(box, sd)
    box.seed_file("f1", "acme-msa.pdf", CONTRACT_TEXT)

    report = pipeline.process("f1")

    # classify, extract, generate_companion, normalize -> 4 chat calls,
    # each billed 1 operation; governance_check is free (no SuperDocs call)
    assert report.total_operations == 4
    by_stage = {s.name: s.operations for s in report.stages}
    assert by_stage["governance_check"] == 0
    assert by_stage["classify"] == 1
    assert by_stage["extract"] == 1
    assert by_stage["generate_companion"] == 1
    assert by_stage["normalize"] == 1
    assert report.total_latency_ms > 0


def test_skipped_companion_stage_costs_nothing():
    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    pipeline = BoxMetadataWritebackPipeline(box, sd)
    box.seed_file("f2", "email.pdf", CORRESPONDENCE_TEXT)

    report = pipeline.process("f2")
    by_stage = {s.name: s for s in report.stages}
    assert by_stage["generate_companion"].status == "skipped"
    assert by_stage["generate_companion"].operations == 0
    # correspondence still costs classify + extract + normalize = 3
    assert report.total_operations == 3


def test_legal_hold_skip_costs_zero_operations():
    from app.models import GovernanceState

    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    pipeline = BoxMetadataWritebackPipeline(box, sd)
    box.seed_file("f3", "sealed.pdf", CONTRACT_TEXT, governance=GovernanceState(legal_hold=True))

    report = pipeline.process("f3")
    assert report.total_operations == 0
