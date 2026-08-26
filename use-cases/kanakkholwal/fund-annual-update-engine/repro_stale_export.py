"""Minimal reproduction: export returns the pre-change document after approval.

One document, one edit, one approval. Exports immediately, then re-exports on a timer until the
approved value actually appears, and prints how long that took.

    python repro_stale_export.py

Needs SUPERDOCS_API_KEY in .env. Costs one operation.
"""

import time
from pathlib import Path

from fund_update.config import load_settings
from fund_update.domain.documents import read_document
from fund_update.domain.plan import read_figures, write_reference_markdown
from fund_update.superdocs.client import SuperDocsClient, save_export

NEW_VALUE = "0.79%"
OLD_VALUE = "0.82%"
POLL_SECONDS = 10
MAX_WAIT = 300


def export_and_read(client: SuperDocsClient, session_id: str, out: Path) -> tuple[bool, bool]:
    body = client.export(session_id, "docx", filename="probe.docx")
    saved = save_export(body, out)
    if not saved:
        return False, False
    text = read_document("factsheet", saved).searchable_text()
    return NEW_VALUE in text, OLD_VALUE in text


def main() -> None:
    settings = load_settings()
    out = settings.out_dir / "repro" / "probe.docx"
    started = time.monotonic()

    def stamp() -> str:
        return f"t+{time.monotonic() - started:6.1f}s"

    with SuperDocsClient(settings.api_key, settings.api_base) as client:
        session_id = client.start_session()
        print(f"{stamp()}  session {session_id}")

        client.upload_document(settings.baseline_dir / "factsheet.docx", session_id)
        reference = write_reference_markdown(
            read_figures(settings.data_file), settings.out_dir / "reference" / "approved-figures.md"
        )
        client.upload_reference(reference, session_id)
        print(f"{stamp()}  uploaded factsheet.docx, attached {reference.name}")

        job = client.request_edit(
            session_id,
            "In this factsheet, where the document says 'Ongoing charges figure', replace the "
            f"value '{OLD_VALUE}' with '{NEW_VALUE}'. Change only that value.",
        )
        print(f"{stamp()}  job {job.job_id} requested")

        state = client.await_job(job.job_id)
        print(f"{stamp()}  job {state.status}, {len(state.changes)} pending change(s)")
        if not state.changes:
            print("no changes proposed; nothing to reproduce")
            return

        client.decide(session_id, job.job_id, [(c.change_id, True, "") for c in state.changes])
        approved_at = time.monotonic()
        print(f"{stamp()}  approved {len(state.changes)} change(s); approve call returned OK")

        has_new, has_old = export_and_read(client, session_id, out)
        print(f"{stamp()}  export #1: new value present={has_new}  old value present={has_old}")
        if has_new:
            print("\nThe first export already contained the change; not reproduced this run.")
            return

        print(f"{stamp()}  ^^ STALE EXPORT: a valid .docx with none of the approved change in it")

        attempt = 1
        while time.monotonic() - approved_at < MAX_WAIT:
            time.sleep(POLL_SECONDS)
            attempt += 1
            has_new, has_old = export_and_read(client, session_id, out)
            print(f"{stamp()}  export #{attempt}: new value present={has_new}  old value present={has_old}")
            if has_new:
                delay = time.monotonic() - approved_at
                print(
                    f"\nReproduced. The approved change appeared {delay:.0f}s after the approve call "
                    f"returned, across {attempt} exports and no other API calls."
                )
                return

        print(f"\nThe change never appeared within {MAX_WAIT}s.")


if __name__ == "__main__":
    main()
