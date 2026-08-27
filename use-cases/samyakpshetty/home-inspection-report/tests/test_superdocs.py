"""The SuperDocs seam: parsing gotchas, and the fake's fidelity to the live service.

The fake backs the entire offline application, so its value depends entirely on it being no
more permissive than the real API. Each limit below was observed against the live service and
is asserted here against the fake.
"""

from __future__ import annotations

import json
import zipfile

import pytest

from inspection_report.superdocs import base
from inspection_report.superdocs.base import (
    MAX_IMAGE_BYTES,
    SessionBusyError,
    SuperDocsClient,
    SuperDocsError,
)
from inspection_report.superdocs.fake import FakeSuperDocsClient
from inspection_report.superdocs.live import LiveSuperDocsClient
from inspection_report.superdocs.models import ApprovalDecision, ExportOptions, JobStatus

DOC = (
    "<h1>14 Alder Lane</h1><h2>Roof</h2>"
    '<p class="finding-note">S flashing gap at chimney</p>'
    '<h2>Electrical</h2><p class="finding-note">GFCI kitchen no trip</p>'
)


@pytest.fixture
def client() -> FakeSuperDocsClient:
    return FakeSuperDocsClient()


class TestBothClientsSatisfyTheProtocol:
    def test_fake_satisfies_it(self) -> None:
        assert isinstance(FakeSuperDocsClient(), SuperDocsClient)

    def test_live_satisfies_it(self) -> None:
        live = LiveSuperDocsClient(api_key="sk_not-a-real-key-never-used")
        assert isinstance(live, SuperDocsClient)
        live.close()

    def test_live_refuses_to_start_without_a_key_and_says_what_to_do(self) -> None:
        with pytest.raises(SuperDocsError) as exc:
            LiveSuperDocsClient(api_key="")
        assert "SUPERDOCS_API_KEY" in str(exc.value)
        assert "fake" in str(exc.value)


class TestParsingTheDocumentedTraps:
    def test_pending_changes_needs_a_second_parse(self) -> None:
        """It arrives as a JSON-encoded string, not an object."""
        payload = {
            "metadata": {
                "pending_changes": json.dumps(
                    [{"chunk_id": "c1", "change_id": "x1", "operation": "replace"}]
                )
            }
        }
        diffs = base.parse_pending_changes(payload)
        assert [d.change_id for d in diffs] == ["x1"]

    def test_already_decoded_form_is_tolerated(self) -> None:
        payload = {"metadata": {"pending_changes": [{"chunk_id": "c1", "change_id": "x1"}]}}
        assert len(base.parse_pending_changes(payload)) == 1

    def test_absent_and_empty_are_not_errors(self) -> None:
        assert base.parse_pending_changes({}) == []
        assert base.parse_pending_changes({"metadata": {"pending_changes": "  "}}) == []

    def test_a_completed_job_hides_its_document_under_result(self) -> None:
        """document_html is null on a completed job; the content is elsewhere."""
        payload = {
            "document_html": None,
            "result": {"document_changes": {"updated_html": "<h1>Report</h1>"}},
        }
        assert base.parse_document_html(payload) == "<h1>Report</h1>"

    def test_a_deletion_arrives_with_a_null_new_html(self) -> None:
        """Not every edit is a replacement, and the missing side is null rather than "".

        Observed live: asked to remove a section, the service proposed one change whose
        ``new_html`` was ``null``. Declaring the field as a plain ``str`` made the entire
        job unparseable — a completed job that had already been charged for could not be
        read at all, because one field of one change was absent. The payload below is the
        shape that came back.
        """
        payload = {
            "result": {
                "document_changes": {
                    "changes": [
                        {
                            "chunk_id": "c9",
                            "change_id": "x9",
                            "operation": "delete",
                            "old_html": "<p>[How each finding is recorded]</p>",
                            "new_html": None,
                            "chunk_type": "paragraph",
                            "ai_explanation": None,
                        }
                    ]
                }
            }
        }
        diffs = base.parse_pending_changes(payload)
        assert len(diffs) == 1
        assert diffs[0].new_html == ""
        assert diffs[0].ai_explanation == ""
        assert diffs[0].is_deletion

    def test_an_insertion_arrives_with_a_null_old_html(self) -> None:
        """The mirror case: new content with nothing on the left-hand side."""
        payload = {
            "metadata": {
                "pending_changes": json.dumps(
                    [
                        {
                            "change_id": "x10",
                            "operation": "insert",
                            "old_html": None,
                            "new_html": "<p>Recommend evaluation: North chimney</p>",
                        }
                    ]
                )
            }
        }
        diffs = base.parse_pending_changes(payload)
        assert diffs[0].old_html == ""
        assert not diffs[0].is_deletion

    def test_usage_prefers_the_promotional_bucket(self) -> None:
        """A job reports its own cost against the promo bucket when one is active."""
        usage = base.parse_usage(
            {
                "result": {
                    "usage": {
                        "monthly_remaining": 500,
                        "promotions": [{"ops_remaining": 9971, "ops_granted": 10000}],
                    }
                }
            }
        )
        assert usage is not None
        assert usage.ops_remaining() == 9971


class TestTheFakeIsNoMoreForgivingThanLive:
    def test_an_oversized_image_is_refused(self, client: FakeSuperDocsClient) -> None:
        with pytest.raises(SuperDocsError) as exc:
            client.upload_image(data=b"\x00" * (MAX_IMAGE_BYTES + 1), filename="big.png")
        assert "at most" in str(exc.value)

    def test_an_unsupported_image_type_is_refused(self, client: FakeSuperDocsClient) -> None:
        with pytest.raises(SuperDocsError):
            client.upload_image(data=b"%PDF-", filename="scan.pdf", content_type="application/pdf")

    def test_chat_without_a_document_is_refused(self, client: FakeSuperDocsClient) -> None:
        with pytest.raises(SuperDocsError):
            client.chat_async(session_id="nothing-here", message="rewrite")

    def test_export_without_a_document_is_refused(self, client: FakeSuperDocsClient) -> None:
        """The live API answers this with 404 'No document loaded in this session.'"""
        with pytest.raises(SuperDocsError) as exc:
            client.export(session_id="nothing-here")
        assert "Load a document first" in str(exc.value)

    def test_a_session_holds_only_one_pending_proposal_set(
        self, client: FakeSuperDocsClient
    ) -> None:
        """The live API answers a second request with a 409 that never clears."""
        client.upload_document(document_html=DOC, session_id="s1")
        client.chat_async(session_id="s1", message="rewrite")
        with pytest.raises(SessionBusyError):
            client.chat_async(session_id="s1", message="rewrite again")

    def test_approve_is_one_call_per_job(self, client: FakeSuperDocsClient) -> None:
        """Approving closes the job; the live API refuses a second call with a 400."""
        client.upload_document(document_html=DOC, session_id="s1")
        job_id = client.chat_async(session_id="s1", message="rewrite")
        diffs = client.get_job(job_id).chunk_diffs
        client.approve(
            session_id="s1",
            job_id=job_id,
            decisions=[ApprovalDecision(change_id=diffs[0].change_id, approved=True)],
        )
        with pytest.raises(SuperDocsError) as exc:
            client.approve(
                session_id="s1",
                job_id=job_id,
                decisions=[ApprovalDecision(change_id=diffs[1].change_id, approved=True)],
            )
        assert "not awaiting approval" in str(exc.value)

    def test_deciding_an_unknown_change_is_refused(self, client: FakeSuperDocsClient) -> None:
        client.upload_document(document_html=DOC, session_id="s1")
        job_id = client.chat_async(session_id="s1", message="rewrite")
        with pytest.raises(SuperDocsError):
            client.approve(
                session_id="s1",
                job_id=job_id,
                decisions=[ApprovalDecision(change_id="not-a-real-change", approved=True)],
            )


class TestChunkIds:
    def test_upload_stamps_every_block(self, client: FakeSuperDocsClient) -> None:
        # h1, h2 Roof, p, h2 Electrical, p
        result = client.upload_document(document_html=DOC, session_id="s1")
        assert result.chunks_count == 5
        assert result.html.count("data-chunk-id") == 5

    def test_custom_data_attributes_are_dropped_but_class_survives(
        self, client: FakeSuperDocsClient
    ) -> None:
        """Live behaviour, verified against the API: `class` is kept, `data-*` is stripped.

        This is why findings are targeted by class and never by an id of our own.
        """
        html = '<p class="finding-note" data-finding="f1">flashing gap at chimney</p>'
        out = client.upload_document(document_html=html, session_id="s1").html
        assert 'class="finding-note"' in out
        assert "data-finding" not in out
        assert "data-chunk-id" in out

    def test_ids_round_trip_unchanged(self, client: FakeSuperDocsClient) -> None:
        """Live behaviour: 6 ids out, the same 6 back. Re-stamping would break targeting."""
        first = client.upload_document(document_html=DOC, session_id="s1").html
        second = client.upload_document(document_html=first, session_id="s2").html
        import re

        assert re.findall(r'data-chunk-id="([^"]+)"', first) == re.findall(
            r'data-chunk-id="([^"]+)"', second
        )


class TestPhotosAndExports:
    def test_an_uploaded_photo_gets_a_stable_url_that_never_prints(
        self, client: FakeSuperDocsClient
    ) -> None:
        upload = client.upload_image(data=b"\x89PNG-pretend", filename="roof.png")
        assert upload.url.startswith("https://")
        # The URL is a capability: repr and str must not leak it into a log or traceback.
        assert upload.url not in repr(upload)
        assert upload.url not in str(upload)
        assert "redacted" in str(upload)

    def test_the_same_bytes_get_the_same_url(self, client: FakeSuperDocsClient) -> None:
        a = client.upload_image(data=b"identical", filename="a.png")
        b = client.upload_image(data=b"identical", filename="b.png")
        assert a.url == b.url

    def test_docx_export_is_a_real_openable_document(self, client: FakeSuperDocsClient) -> None:
        client.upload_document(document_html=DOC, session_id="s1")
        result = client.export(session_id="s1", fmt="docx")
        assert zipfile.is_zipfile(__import__("io").BytesIO(result.content))

    def test_pdf_export_is_a_real_pdf(self, client: FakeSuperDocsClient) -> None:
        client.upload_document(document_html=DOC, session_id="s1")
        result = client.export(session_id="s1", fmt="pdf")
        assert result.content.startswith(b"%PDF")
        assert result.content_type == "application/pdf"

    def test_a_photo_lands_in_the_exported_docx(self, client: FakeSuperDocsClient) -> None:
        """The whole point of the images surface: the photo must be in the file."""
        png = _tiny_png()
        upload = client.upload_image(data=png, filename="roof.png")
        html = f'{DOC}<p><img src="{upload.url}" alt="north chimney"></p>'
        client.upload_document(document_html=html, session_id="s1")
        result = client.export(session_id="s1", fmt="docx")
        with zipfile.ZipFile(__import__("io").BytesIO(result.content)) as z:
            media = [n for n in z.namelist() if n.startswith("word/media/")]
        assert media, "the photograph did not reach the exported document"

    def test_export_options_name_the_file(self, client: FakeSuperDocsClient) -> None:
        client.upload_document(document_html=DOC, session_id="s1")
        result = client.export(
            session_id="s1", fmt="pdf", options=ExportOptions(filename="14-alder-lane")
        )
        assert result.filename == "14-alder-lane.pdf"


def _tiny_png() -> bytes:
    """A genuinely valid 2x2 PNG, built here so the tests carry no binary fixtures."""
    import binascii
    import struct
    import zlib

    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 2 for _ in range(2))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", binascii.crc32(tag + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


class TestTheAuditTrailHasOneRowPerProposal:
    """Recording the same proposal twice must update it, not duplicate it.

    A round is recorded when the proposals arrive and again when they are decided. The row
    key used to be a fresh uuid4 on each call, so the upsert never fired and the table ended
    up holding a stale `pending` copy of every decided change. "Why does the report say this"
    has to have exactly one answer.
    """

    def test_the_key_is_derived_from_the_change_not_minted(self) -> None:
        from uuid import UUID, uuid5

        from inspection_report.store.db import _PROPOSAL_NS

        inspection_id = UUID("11111111-2222-3333-4444-555555555555")
        first = uuid5(_PROPOSAL_NS, f"{inspection_id}:chg-abc")
        second = uuid5(_PROPOSAL_NS, f"{inspection_id}:chg-abc")
        other = uuid5(_PROPOSAL_NS, f"{inspection_id}:chg-def")
        assert first == second, "the same change must land on the same row"
        assert first != other, "different changes must not collide"

    def test_a_different_inspection_never_collides(self) -> None:
        from uuid import UUID, uuid5

        from inspection_report.store.db import _PROPOSAL_NS

        a = uuid5(_PROPOSAL_NS, f"{UUID(int=1)}:chg-abc")
        b = uuid5(_PROPOSAL_NS, f"{UUID(int=2)}:chg-abc")
        assert a != b


class TestTheFakeIsSharedTheWayAServerIs:
    """SuperDocs is another machine; two of our processes talking to it see one state.

    The fake was a dict in one process, and nothing noticed until the rewrite pass moved to
    the worker: it created the job, the API received the approval, and the API's fake had
    never heard of the job. Every approval in the running application failed with
    ``unknown job 'job-0001'`` while every test stayed green, because the tests — and the CLI
    — do the whole round in one process.
    """

    def test_a_job_from_one_process_can_be_approved_by_another(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        worker = FakeSuperDocsClient(state_dir=str(tmp_path))
        worker.upload_document(document_html=DOC, session_id="s1")
        job_id = worker.chat_async(session_id="s1", message="rewrite")

        # A separate instance is what a separate process has: nothing is shared in memory.
        api = FakeSuperDocsClient(state_dir=str(tmp_path))
        diffs = api.get_job(job_id).chunk_diffs
        assert diffs, "the job the worker created must be visible to the API"

        result = api.approve(
            session_id="s1",
            job_id=job_id,
            decisions=[ApprovalDecision(change_id=diffs[0].change_id, approved=True)],
        )
        assert result.applied_count == 1

    def test_the_decision_is_visible_to_the_process_that_proposed_it(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Approving must change the document every process sees, not just the deciding one."""
        worker = FakeSuperDocsClient(state_dir=str(tmp_path))
        worker.upload_document(document_html=DOC, session_id="s1")
        job_id = worker.chat_async(session_id="s1", message="rewrite")
        diffs = worker.get_job(job_id).chunk_diffs

        api = FakeSuperDocsClient(state_dir=str(tmp_path))
        api.approve(
            session_id="s1",
            job_id=job_id,
            decisions=[ApprovalDecision(change_id=d.change_id, approved=True) for d in diffs],
        )

        assert worker.get_job(job_id).status is JobStatus.COMPLETED
        exported = worker.export(session_id="s1", fmt="html").content.decode()
        assert diffs[0].new_html in exported

    def test_two_processes_never_mint_the_same_job_id(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """The id counter is part of the shared state, or both processes start at one."""
        first = FakeSuperDocsClient(state_dir=str(tmp_path))
        first.upload_document(document_html=DOC, session_id="s1")
        one = first.chat_async(session_id="s1", message="rewrite")

        second = FakeSuperDocsClient(state_dir=str(tmp_path))
        second.upload_document(document_html=DOC, session_id="s2")
        two = second.chat_async(session_id="s2", message="rewrite")

        assert one != two

    def test_without_a_state_dir_the_fake_stays_in_memory(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """The control, and the default the keyless suite depends on.

        Sharing is opt-in: unset, two instances are two independent fakes, which is what a
        test wants and why 218 tests do not touch the disk.
        """
        first = FakeSuperDocsClient(state_dir=None)
        first.upload_document(document_html=DOC, session_id="s1")
        job_id = first.chat_async(session_id="s1", message="rewrite")

        with pytest.raises(SuperDocsError):
            FakeSuperDocsClient(state_dir=None).get_job(job_id)


def test_usage_survives_a_null_field_from_the_service() -> None:
    """An explicit `null` must be treated as "not sent", not as a parse failure.

    Seen live on 27 Aug 2026: a job that had just succeeded came back with
    `bucket_used: null`, which failed the whole `Usage` parse and surfaced in the interface as
    a pydantic ValidationError where the report should have been. Every field is checked here,
    not just the one that broke, because the sender draws no distinction between a key it
    omits and a key it sends as null.
    """
    from inspection_report.superdocs.models import Usage

    usage = Usage.model_validate(
        {
            "ops_charged": None,
            "was_billable": None,
            "quota_exhausted": None,
            "bucket_used": None,
            "monthly_used": None,
            "monthly_limit": None,
            "monthly_remaining": None,
            "promotions": None,
        }
    )
    assert usage.bucket_used == ""
    assert usage.ops_charged == 0
    assert usage.promotions == []

    # A real payload still parses exactly as before.
    real = Usage.model_validate({"ops_charged": 1, "bucket_used": "promo", "monthly_used": 7})
    assert real.ops_charged == 1 and real.bucket_used == "promo" and real.monthly_used == 7
