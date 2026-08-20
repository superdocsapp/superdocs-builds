"""Tests for the orchestration logic in generator.py, against a fake client
(not real HTTP) -- these are testing OUR logic: does it call approve() only
when needed, does it name the output file correctly, does it scope the AI
instruction to only the one section that needs real synthesis.
"""

import pytest

from battlecard.generator import CompetitorInput, _build_instruction, generate_battlecard
from battlecard.superdocs_client import ChatJobResult, ExportResult, JobStatusResult, UploadResult


class FakeClient:
    """Records every call so tests can assert on exactly what happened,
    without touching the network."""

    def __init__(self, job_status: str):
        self.job_status = job_status
        self.approve_calls = []
        self.uploaded_filenames = []
        self.instructions = []

    def upload_document(self, file_bytes, filename):
        self.uploaded_filenames.append(filename)
        return UploadResult(session_id="sess_fake", filename=filename, persisted=True)

    def start_edit(self, session_id, instruction):
        self.instructions.append(instruction)
        return ChatJobResult(job_id="job_fake", session_id=session_id, status="pending")

    def wait_for_completion(self, job_id, **kwargs):
        return JobStatusResult(status=self.job_status, updated_html="<p>done</p>", raw={})

    def approve(self, session_id, job_id, approved):
        self.approve_calls.append((session_id, job_id, approved))

    def export(self, session_id, format="docx"):
        return ExportResult(file_bytes=b"fake-exported-bytes", filename="whatever.docx", content_type="application/octet-stream")


ZEPHYR = CompetitorInput(
    name="Zephyr Analytics",
    likely_pitch="Fastest dashboard to set up, no engineering needed.",
    where_we_win="Reports stay accurate when the data model changes.",
    where_we_dont="Their onboarding is genuinely faster out of the box.",
)

BRIGHTFIELD = CompetitorInput(
    name="Brightfield",
    likely_pitch="Enterprise-grade governance and audit trails.",
    where_we_win="We ship new integrations in days, not quarters.",
    where_we_dont="Their compliance certifications are more extensive.",
)


def test_skips_approve_when_job_already_auto_completed(tmp_path):
    """Real bug found live on a different SuperDocs build: calling approve()
    on an already-completed job 400s. The generator must check status first."""
    client = FakeClient(job_status="completed")
    generate_battlecard(client, ZEPHYR, tmp_path)
    assert client.approve_calls == []


def test_calls_approve_when_job_is_awaiting_approval(tmp_path):
    client = FakeClient(job_status="awaiting_approval")
    generate_battlecard(client, ZEPHYR, tmp_path)
    assert client.approve_calls == [("sess_fake", "job_fake", True)]


def test_raises_on_failed_job(tmp_path):
    client = FakeClient(job_status="failed")
    with pytest.raises(RuntimeError):
        generate_battlecard(client, ZEPHYR, tmp_path)


def test_writes_output_file_named_after_competitor(tmp_path):
    client = FakeClient(job_status="completed")
    out_path = generate_battlecard(client, ZEPHYR, tmp_path, export_format="docx")
    assert out_path.name == "battlecard-Zephyr_Analytics.docx"
    assert out_path.read_bytes() == b"fake-exported-bytes"


def test_ai_instruction_is_scoped_to_only_the_talk_track_section():
    """Found by testing live: asking the model to fill three known fields
    plus synthesize one, in a single call, was unreliable across identical
    runs. The known fields are templated locally (see test_template.py);
    the AI is only asked for the one sentence that needs real judgment."""
    instruction = _build_instruction(ZEPHYR)
    assert "Talk Track" in instruction
    assert "Their Pitch" not in instruction
    assert "Where We Win" not in instruction
    assert ZEPHYR.where_we_win in instruction
    assert ZEPHYR.where_we_dont in instruction
    assert "Do not change any other section" in instruction


def test_two_competitors_produce_different_instructions():
    zephyr_instruction = _build_instruction(ZEPHYR)
    brightfield_instruction = _build_instruction(BRIGHTFIELD)
    assert zephyr_instruction != brightfield_instruction
    assert ZEPHYR.where_we_win in zephyr_instruction
    assert ZEPHYR.where_we_win not in brightfield_instruction
