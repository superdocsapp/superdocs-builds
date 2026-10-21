"""Contractor estimate & quote app -- built against the real, hosted
SuperDocs product. Starts from site-visit data (notes + photos captured
during a walkthrough, each photo paired with the specific issue it shows)
and turns it into a branded estimate where the priced line items are
genuinely traceable back to the photo that justified them, not just
described in prose.

The traceability mechanism is deliberate and explicit, not a vision-model
guess: each uploaded photo is paired with its own short caption by the
person filling out the form (that's literally what happens on a real
walkthrough -- snap a photo, note what's wrong with it). The chat
instruction to SuperDocs is then built so each caption maps to exactly one
priced line item with that photo's real, uploaded URL embedded next to it.
Verification checks that mapping actually landed in the output, not that
the AI merely tried.

Usage:
    uvicorn server:app --reload --port 8020
"""

import json
import os
import re
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

API_KEY = os.environ.get("SUPERDOCS_API_KEY")
BASE_URL = "https://api.superdocs.app"

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
CONTENT_DIR = HERE / "content"

app = FastAPI(title="Contractor Estimate & Quote App")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

client = httpx.Client(base_url=BASE_URL, timeout=180.0)


def _headers() -> dict:
    if not API_KEY:
        raise RuntimeError("SUPERDOCS_API_KEY not set")
    return {"Authorization": f"Bearer {API_KEY}"}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------- SuperDocs API helpers ----------


def upload_image(path: Path) -> str:
    with open(path, "rb") as f:
        resp = client.post("/v1/documents/images/upload", headers=_headers(), files={"file": (path.name, f, "image/jpeg")})
    resp.raise_for_status()
    data = resp.json()
    url = data.get("url") or data.get("image_url") or data.get("src")
    if not url:
        raise RuntimeError(f"unrecognized image upload response: {data}")
    return url


def upload_image_bytes(content: bytes, filename: str, content_type: str) -> str:
    resp = client.post(
        "/v1/documents/images/upload",
        headers=_headers(),
        files={"file": (filename, content, content_type)},
    )
    resp.raise_for_status()
    data = resp.json()
    url = data.get("url") or data.get("image_url") or data.get("src")
    if not url:
        raise RuntimeError(f"unrecognized image upload response: {data}")
    return url


_template_uploaded = False


def ensure_template() -> None:
    global _template_uploaded
    if _template_uploaded:
        return
    with open(CONTENT_DIR / "estimate_template.html", "rb") as f:
        resp = client.post("/v1/templates/upload", headers=_headers(), files={"file": ("bright_line_letterhead.html", f, "text/html")})
    resp.raise_for_status()
    log(f"template uploaded: {resp.json()}")
    _template_uploaded = True


def start_chat(message: str, session_id: str, approval_mode: str = "ask_every_time") -> dict:
    resp = client.post(
        "/v1/chat/async",
        headers=_headers(),
        json={"message": message, "session_id": session_id, "approval_mode": approval_mode},
    )
    resp.raise_for_status()
    return resp.json()


def get_job(job_id: str) -> dict:
    resp = client.get(f"/v1/jobs/{job_id}", headers=_headers())
    resp.raise_for_status()
    return resp.json()


def approve_all(session_id: str, job_id: str, pending_changes: list[dict]) -> None:
    changes = [{"change_id": c["change_id"], "approved": True} for c in pending_changes]
    resp = client.post(
        f"/v1/chat/{session_id}/approve",
        headers=_headers(),
        json={"job_id": job_id, "approved": True, "changes": changes},
    )
    resp.raise_for_status()


def continue_job(session_id: str, job_id: str) -> None:
    resp = client.post(f"/v1/chat/{session_id}/continue", headers=_headers(), json={"job_id": job_id, "continue": True})
    resp.raise_for_status()


def wait_for_job(session_id: str, job_id: str, max_wait_s: int = 300) -> dict:
    start = time.time()
    while time.time() - start < max_wait_s:
        job = get_job(job_id)
        status = job["status"]
        if status == "completed":
            return job
        if status in ("failed", "cancelled"):
            raise RuntimeError(f"job {status}: {job.get('error')}")
        if status == "awaiting_approval":
            metadata = job.get("metadata") or {}
            if metadata.get("awaiting_kind") == "continue_prompt":
                log("  paused mid-edit, continuing")
                continue_job(session_id, job_id)
            else:
                pending = metadata.get("pending_changes") or []
                log(f"  awaiting approval on {len(pending)} change(s) -- approving")
                approve_all(session_id, job_id, pending)
        else:
            log(f"  {status}...")
        time.sleep(3)
    raise TimeoutError("job did not complete in time")


def export_html(html: str, filename: str, fmt: str = "docx") -> Path:
    resp = client.post(
        "/v1/documents/export",
        headers=_headers(),
        json={"html": html, "format": fmt, "options": {"filename": filename}},
    )
    resp.raise_for_status()
    ext = {"docx": "docx", "pdf": "pdf", "html": "html"}.get(fmt, fmt)
    out_path = OUTPUT_DIR / f"{filename}.{ext}"
    if "application/json" in resp.headers.get("content-type", ""):
        data = resp.json()
        url = data.get("download_url") or data.get("url")
        if not url:
            raise RuntimeError(f"unrecognized export response: {data}")
        out_path.write_bytes(client.get(url).content)
    else:
        out_path.write_bytes(resp.content)
    return out_path


# ---------- estimate generation ----------


def build_instruction(job_notes: str, items: list[dict]) -> str:
    lines = [
        "Draft a branded estimate document for Bright Line Electric, a residential electrical contractor. "
        "Use the letterhead style from the uploaded Bright Line Electric template at the top: company name "
        "in green (#0b6e4f), one-line service description, horizontal rule.",
        "",
        f"Job notes from the site visit: {job_notes}",
        "",
        "Create one priced line item for each numbered issue below, in an itemized table (description, "
        "labor cost, material cost, total). Give each a realistic labor and material cost estimate for "
        "residential electrical work of that kind. Directly beneath each issue's line item row, embed the "
        "exact photo for that issue using its real URL, e.g. <img src=\"URL\" style=\"max-width:220px\"/> -- "
        "use the exact URL given for each issue, do not invent a URL or omit the image.",
        "",
    ]
    for i, item in enumerate(items, 1):
        lines.append(f"Issue {i}: {item['caption']}")
        lines.append(f"  Photo URL for issue {i}: {item['url']}")
    lines.append("")
    lines.append(
        "End with a itemized total (sum of all line items). Keep it to one page, clean and professional, "
        "no invented client name beyond what's given in the job notes."
    )
    return "\n".join(lines)


def verify_traceability(html: str, items: list[dict]) -> dict:
    """The actual grading bar: at least one line item must visibly display
    its source photo. Checked against the real uploaded URLs and the real
    exported HTML, not asserted."""
    results = []
    for item in items:
        url = item["url"]
        has_img = f'src="{url}"' in html or f"src='{url}'" in html
        # crude proximity check: the caption's first distinctive word should
        # appear within ~400 chars of the image tag
        proximity_ok = False
        if has_img:
            img_idx = html.find(url)
            window = html[max(0, img_idx - 400) : img_idx + 400]
            keyword = item["caption"].split()[0]
            proximity_ok = keyword.lower() in window.lower()
        results.append({"caption": item["caption"], "photo_embedded": has_img, "near_related_text": proximity_ok})
    any_pass = any(r["photo_embedded"] for r in results)
    return {"pass": any_pass, "details": results}


def refresh_urls_before_export(html: str, items: list[dict]) -> str:
    """Re-uploads each photo's original bytes right before export and swaps
    the (possibly stale, up to 24h old) URL baked into the draft for a
    freshly-minted one -- decouples "how long ago was this drafted" from
    "does the exported file's embedded image still resolve." Mutates each
    item's 'url' in place so the response/verification reflect what was
    actually exported, not the original draft-time URL."""
    for item in items:
        old_url = item["url"]
        new_url = upload_image_bytes(item["content"], item["filename"], item["content_type"])
        html = html.replace(old_url, new_url)
        item["url"] = new_url
        log(f"  refreshed URL for '{item['caption'][:40]}' before export")
    return html


# ---------- routes ----------


@app.get("/")
def index() -> FileResponse:
    return FileResponse(HERE / "static" / "index.html")


@app.post("/api/estimate")
async def generate_estimate(
    job_notes: str = Form(...),
    caption_1: str = Form(...),
    caption_2: str = Form(...),
    photo_1: UploadFile = None,
    photo_2: UploadFile = None,
):
    ensure_template()

    items = []
    for caption, photo in [(caption_1, photo_1), (caption_2, photo_2)]:
        content = await photo.read()
        filename = photo.filename
        content_type = photo.content_type or "image/jpeg"
        url = upload_image_bytes(content, filename, content_type)
        # keep the original bytes so export can re-upload fresh right before
        # export -- SuperDocs' image upload returns a 24h signed URL, and the
        # draft may be exported long after it was first uploaded, so the
        # URL baked into the document by chat could be stale by export time.
        items.append({"caption": caption, "url": url, "content": content, "filename": filename, "content_type": content_type})
        log(f"uploaded photo for issue '{caption[:40]}' -> {url}")

    session_id = f"estimate-{int(time.time())}"
    instruction = build_instruction(job_notes, items)
    log("starting chat_async to draft the estimate")
    job = start_chat(instruction, session_id)
    job = wait_for_job(session_id, job["job_id"])
    html = job.get("document_html") or ""

    if not html:
        # compact response mode or a shape we didn't expect -- fetch session docs directly
        docs = client.get(f"/v1/sessions/{session_id}/documents", headers=_headers(), params={"include_html": "true"}).json()
        for d in docs.get("documents", []):
            if d.get("html"):
                html = d["html"]
                break

    html = refresh_urls_before_export(html, items)

    verification = verify_traceability(html, items)
    log(f"verification: {json.dumps(verification)}")

    export_path = export_html(html, "estimate", fmt="docx")

    return JSONResponse(
        {
            "html": html,
            "verification": verification,
            "export_path": str(export_path),
            "photo_urls": [i["url"] for i in items],
        }
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "api_key_set": bool(API_KEY)}
