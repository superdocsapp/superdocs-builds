"""Proof that a run killed partway through the four-stage pipeline
resumes from the first *incomplete* stage on the next process() call,
rather than redoing stages that already succeeded.

This is proven the hard way: rather than trusting that "it finished
without error" implies nothing was redone (a whole-run restart would
also finish), every test here inspects FakeSuperDocsClient.call_log
directly to assert exactly which instructions were actually sent to
SuperDocs, before and after a simulated kill.
"""
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.workflow.checkpoint import CheckpointStore
from app.workflow.pipeline import BoxMetadataWritebackPipeline

REPO_ROOT = str(Path(__file__).resolve().parents[1])

CONTRACT_TEXT = b"""SERVICES AGREEMENT
Counterparty: Acme Logistics Inc
Effective Date: 2026-01-15
Expiration Date: 2027-01-14
Value: $84,000
This agreement governs the provision of freight brokerage services.
"""


def make_pipeline(checkpoint=None):
    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    pipeline = BoxMetadataWritebackPipeline(
        box, sd, checkpoint=checkpoint or CheckpointStore(), retry_sleep_fn=lambda seconds: None
    )
    return box, sd, pipeline


def test_full_run_makes_exactly_one_chat_call_per_stage_and_clears_its_checkpoint():
    checkpoint = CheckpointStore()
    box, sd, pipeline = make_pipeline(checkpoint)
    box.seed_file("file-1", "acme-msa.pdf", CONTRACT_TEXT)
    version = box.get_file_version("file-1")

    report = pipeline.process("file-1")

    assert report.skipped_reason is None
    assert [s.status for s in report.stages] == ["done"] * 5  # governance + 4 SuperDocs stages
    assert len(sd.call_log) == 4  # classify, extract, companion, normalize -- one call each
    # A successfully committed run doesn't leave a checkpoint behind --
    # there's nothing left to resume.
    assert checkpoint.get("file-1", version.sha1) is None


def test_resuming_from_a_pre_kill_checkpoint_skips_completed_stages():
    """Simulates the exact state a kill between 'extract' finishing and
    'companion' starting would leave in the checkpoint store (which is
    persisted the instant each stage finishes -- see
    _checkpoint_stage_if_done), then proves the next process() call
    replays classify+extract for free and only calls SuperDocs for the
    two stages that never finished."""
    checkpoint = CheckpointStore()
    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    box.seed_file("file-2", "acme-msa.pdf", CONTRACT_TEXT)
    version = box.get_file_version("file-2")
    pipeline = BoxMetadataWritebackPipeline(box, sd, checkpoint=checkpoint, retry_sleep_fn=lambda s: None)

    checkpoint.save_stage(
        "file-2",
        version.sha1,
        "classify",
        {"name": "classify", "status": "done", "detail": "pre-seeded", "latency_ms": 0, "operations": 1},
        {"doc_class": "contract", "doc_class_confidence": 0.95},
    )
    checkpoint.save_stage(
        "file-2",
        version.sha1,
        "extract",
        {"name": "extract", "status": "done", "detail": "pre-seeded", "latency_ms": 0, "operations": 1},
        {
            "doc_class": "contract",
            "doc_class_confidence": 0.95,
            "counterparty_name": "Acme Logistics Inc",
            "effective_date": "2026-01-15",
        },
    )

    report = pipeline.process("file-2")

    assert report.skipped_reason is None
    assert [s.status for s in report.stages] == ["done"] * 5

    # The critical assertion: classify/extract were never re-sent to
    # SuperDocs. Only the two genuinely-incomplete stages were.
    assert len(sd.call_log) == 2
    assert not any("classify" in c.lower() for c in sd.call_log)
    assert not any("extract key terms" in c.lower() for c in sd.call_log)
    assert any("companion" in c.lower() for c in sd.call_log)
    assert any("normalize" in c.lower() for c in sd.call_log)

    # Resumed stages show up honestly in the report as zero-cost.
    classify_stage = next(s for s in report.stages if s.name == "classify")
    extract_stage = next(s for s in report.stages if s.name == "extract")
    assert "resumed from checkpoint" in classify_stage.detail
    assert "resumed from checkpoint" in extract_stage.detail
    assert classify_stage.operations == 0
    assert extract_stage.operations == 0

    # Extracted state genuinely carried through the resume.
    assert report.metadata_written["counterparty_name"] == "Acme Logistics Inc"
    assert report.metadata_written["effective_date"] == "2026-01-15"

    # Terminal success clears the checkpoint.
    assert checkpoint.get("file-2", version.sha1) is None


def test_a_genuinely_killed_process_resumes_via_persisted_checkpoint():
    """The real proof: two separate `python3` subprocess invocations, not
    two Python objects in one interpreter. Process 1 completes classify
    and extract (persisting each to a shared SQLite checkpoint file) and
    then calls os._exit() -- which skips `finally` blocks and atexit
    handlers, the closest a subprocess test can get to a real SIGKILL --
    before companion/normalize ever run. Process 2, started fresh against
    the same checkpoint file, calls the ordinary process() entrypoint and
    is proven to have never re-sent classify/extract to its own
    (separate) SuperDocs client."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/checkpoint.db"
        marker_path = f"{tmp}/reached_kill_point.marker"

        first_process = textwrap.dedent(
            f"""
            import os, sys
            sys.path.insert(0, {REPO_ROOT!r})
            from app.clients.fake_box_client import FakeBoxClient
            from app.clients.fake_superdocs_client import FakeSuperDocsClient
            from app.storage.sqlite_backend import SqliteCheckpointStore
            from app.workflow.pipeline import BoxMetadataWritebackPipeline, RunReport
            from app.models import ExtractedFields

            box = FakeBoxClient()
            sd = FakeSuperDocsClient()
            checkpoint = SqliteCheckpointStore({db_path!r})
            pipeline = BoxMetadataWritebackPipeline(
                box, sd, checkpoint=checkpoint, retry_sleep_fn=lambda s: None
            )
            box.seed_file("file-x", "acme.pdf", {CONTRACT_TEXT!r})
            version = box.get_file_version("file-x")

            doc_id = sd.upload(version.name, box.download_file("file-x"))
            report = RunReport(file_id="file-x", version_sha1=version.sha1)

            extracted = pipeline._run_stage_classify(doc_id, ExtractedFields(), report)
            pipeline._checkpoint_stage_if_done("file-x", version.sha1, "classify", report, extracted)

            extracted = pipeline._run_stage_extract(doc_id, extracted, report, "file-x", version.sha1)
            pipeline._checkpoint_stage_if_done("file-x", version.sha1, "extract", report, extracted)

            assert len(sd.call_log) == 2  # classify once, extract once
            open({marker_path!r}, "w").close()

            os._exit(1)  # simulated SIGKILL -- returncode 1 is EXPECTED, no finally/atexit runs
            """
        )
        result1 = subprocess.run([sys.executable, "-c", first_process], capture_output=True, text=True)
        assert result1.returncode == 1, f"stdout={result1.stdout} stderr={result1.stderr}"
        assert Path(marker_path).exists(), f"process 1 didn't reach the kill point: {result1.stderr}"

        second_process = textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {REPO_ROOT!r})
            from app.clients.fake_box_client import FakeBoxClient
            from app.clients.fake_superdocs_client import FakeSuperDocsClient
            from app.storage.sqlite_backend import SqliteCheckpointStore
            from app.workflow.pipeline import BoxMetadataWritebackPipeline

            box = FakeBoxClient()
            sd = FakeSuperDocsClient()
            checkpoint = SqliteCheckpointStore({db_path!r})
            pipeline = BoxMetadataWritebackPipeline(
                box, sd, checkpoint=checkpoint, retry_sleep_fn=lambda s: None
            )
            box.seed_file("file-x", "acme.pdf", {CONTRACT_TEXT!r})

            report = pipeline.process("file-x")
            assert report.skipped_reason is None, report.skipped_reason
            assert [s.status for s in report.stages] == ["done"] * 5, report.stages

            # This SECOND process's own SuperDocs client never saw
            # classify/extract -- those were persisted by process 1 and
            # replayed from the shared SQLite file, not redone.
            assert not any("classify" in c.lower() for c in sd.call_log), sd.call_log
            assert not any("extract key terms" in c.lower() for c in sd.call_log), sd.call_log
            assert len(sd.call_log) == 2, sd.call_log
            print("RESUME_OK")
            """
        )
        result2 = subprocess.run([sys.executable, "-c", second_process], capture_output=True, text=True)
        assert result2.returncode == 0, f"stdout={result2.stdout} stderr={result2.stderr}"
        assert "RESUME_OK" in result2.stdout
