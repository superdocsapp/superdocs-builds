from __future__ import annotations

import os
import time
import unittest
import uuid

from paper_scaffolder.superdocs import SuperDocsHttpAdapter, SuperDocsSettings


LIVE_ENABLED = bool(os.getenv("SUPERDOCS_API_KEY")) and os.getenv(
    "RUN_SUPERDOCS_LIVE_TESTS"
) == "1"


@unittest.skipUnless(
    LIVE_ENABLED,
    "Set SUPERDOCS_API_KEY and RUN_SUPERDOCS_LIVE_TESTS=1 to run live integration.",
)
class SuperDocsLiveTests(unittest.TestCase):
    def test_upload_review_reject_and_export(self) -> None:
        adapter = SuperDocsHttpAdapter(SuperDocsSettings.from_environment())
        session_id = f"paper-scaffolder-live-{uuid.uuid4().hex[:12]}"
        uploaded = adapter.upload_document(
            filename="paper-scaffolder-live.html",
            content=(
                b"<!doctype html><html><body><h1>Test Manuscript</h1>"
                b"<h2>Methods</h2><p>We used interviews.</p>"
                b"<h2>Results</h2><p>[No verified results were provided.]</p>"
                b"</body></html>"
            ),
            session_id=session_id,
        )
        job = adapter.send_edit_instruction(
            session_id=uploaded.session_id,
            instruction=(
                "Change only the heading 'Methods' to 'Methodology'. "
                "Do not alter or add research findings."
            ),
        )

        deadline = time.monotonic() + 180
        saw_proposed_change = False
        while time.monotonic() < deadline:
            snapshot = adapter.get_job(job_id=job.job_id)
            if snapshot.status == "awaiting_approval":
                self.assertNotEqual(snapshot.awaiting_kind, "continue_prompt")
                self.assertTrue(snapshot.proposed_changes)
                saw_proposed_change = True
                for change in snapshot.proposed_changes:
                    adapter.reject_change(
                        session_id=uploaded.session_id,
                        job_id=job.job_id,
                        change_id=change.change_id,
                        feedback="Live contract test: deny the proposed edit.",
                    )
            elif snapshot.status == "completed":
                break
            elif snapshot.status in {"failed", "cancelled"}:
                self.fail(snapshot.error or f"Live job ended as {snapshot.status}")
            time.sleep(2)
        else:
            self.fail("Live SuperDocs job did not complete before the deadline.")

        self.assertTrue(saw_proposed_change)
        exported = adapter.export_document(
            session_id=uploaded.session_id,
            file_format="html",
            filename="paper-scaffolder-live",
        )
        self.assertTrue(exported.content)


if __name__ == "__main__":
    unittest.main()
