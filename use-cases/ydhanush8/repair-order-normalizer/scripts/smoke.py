"""One order, one live round trip, every response shape printed.

Deliberately a single order: this is where assumptions meet the real API, and it
costs one operation out of ten thousand. Nothing is inferred — whatever comes
back is printed so the client can be corrected against it rather than against a
guess.

    python scripts/smoke.py            # mock, free
    python scripts/smoke.py --live     # the real API
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402

from ro_normalizer import config  # noqa: E402
from ro_normalizer.normalizer import normalize  # noqa: E402
from ro_normalizer.schemas import Element  # noqa: E402
from ro_normalizer.services.batch import load_orders  # noqa: E402
from ro_normalizer.services.pipeline import build_instruction, build_source_document  # noqa: E402

REDACT = ("api_key", "authorization", "token", "secret")


def show(label: str, payload: object) -> None:
    text = json.dumps(payload, indent=1, default=str) if not isinstance(payload, str) else payload
    for word in REDACT:
        if word in text.lower():
            text = "<redacted: response mentioned a credential>"
            break
    print(f"\n── {label} " + "─" * max(0, 60 - len(label)))
    print(text[:1800])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="call the real API")
    args = parser.parse_args()

    backend = "superdocs" if args.live else "mock"
    order = load_orders(Path(__file__).parents[1] / "sample-data" / "orders.json")[0]
    result = normalize(order)

    print(f"backend: {backend}")
    print(f"order:   {order.repair_order_id}  confidence {result.confidence.value}")

    if not args.live:
        editor = config.build_editor("mock")
        ref = editor.upload(f"{order.repair_order_id}.txt", build_source_document(order))
        proposed = editor.propose_edit(ref.document_id, build_instruction([Element.COMPLAINT], result))
        editor.approve(ref.document_id, [c.change_id for c in proposed.changes])
        show("exported", editor.export(ref.document_id))
        return 0

    # --- live -------------------------------------------------------------
    # Raw calls rather than the client, so the true response shapes are visible
    # before anything is parsed into our own types.
    import base64
    import time
    import uuid

    key = config.get("SUPERDOCS_API_KEY")
    if not key:
        print("SUPERDOCS_API_KEY is empty in .env")
        return 1

    client = httpx.Client(
        base_url=config.get("SUPERDOCS_BASE_URL") or "https://api.superdocs.app",
        timeout=float(config.get("SUPERDOCS_TIMEOUT_SECONDS", "300")),
        headers={"Authorization": f"Bearer {key}"},
    )
    session_id = str(uuid.uuid4())
    document = build_source_document(order)
    document_html = (
        "<html><body>"
        + "".join(f"<p>{block.strip()}</p>" for block in document.split("\n\n") if block.strip())
        + "</body></html>"
    )

    print(f"\nsession: {session_id}")

    # The documentation says `document_html`; the API answered 422 asking for
    # `filename` and `file_base64`. The API wins.
    response = client.post(
        "/v1/documents/upload-base64",
        json={
            "filename": f"{order.repair_order_id}.html",
            "file_base64": base64.b64encode(document_html.encode()).decode(),
            "session_id": session_id,
        },
    )
    print(f"\nPOST /v1/documents/upload-base64 -> {response.status_code}")
    if response.status_code >= 400:
        show("error body", response.text)
        return 1
    upload = response.json()
    show("upload response keys", sorted(upload.keys()) if isinstance(upload, dict) else upload)

    instruction = build_instruction([Element.COMPLAINT], result)
    response = client.post(
        "/v1/chat/async",
        json={
            "message": instruction,
            "session_id": session_id,
            # The docs imply a boolean; the API rejects one and wants a string.
            # "manual" is what it accepts.
            "approval_mode": "manual",
        },
    )
    print(f"\nPOST /v1/chat/async -> {response.status_code}")
    if response.status_code >= 400:
        show("error body", response.text)
        return 1
    job = response.json()
    show("chat response", job)

    job_id = job.get("job_id")
    if not job_id:
        print("no job_id — the flow may be synchronous for this account")
        return 1

    state: dict = {}
    for attempt in range(60):
        state = client.get(f"/v1/jobs/{job_id}").json()
        status = state.get("status")
        print(f"  poll {attempt + 1}: {status}")
        if status in {"awaiting_approval", "completed", "failed"}:
            break
        time.sleep(3)

    show("job state keys", sorted(state.keys()))
    show("job metadata", state.get("metadata"))
    show("usage", state.get("usage"))

    pending = (state.get("metadata") or {}).get("pending_changes")
    print(f"\npending_changes type: {type(pending).__name__}")
    if pending:
        first = pending[0] if isinstance(pending, list) else pending
        show("first pending change", first)
        print(
            "\nSHAPE VERDICT: "
            + (
                "JSON-encoded string — the task document is right"
                if isinstance(pending, str)
                else "structured objects — the current documentation is right"
            )
        )

    print("\nStopping before approve/export so nothing is written and no further")
    print("operations are spent. Re-run with the client once the shapes are confirmed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
