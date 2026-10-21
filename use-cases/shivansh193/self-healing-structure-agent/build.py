"""Self-Healing Document Agent for Structure and Numbering -- built against
the real, hosted SuperDocs product. Takes a document whose Section
numbering has drifted (a skipped number, a duplicated number, numbers that
run past the actual Section count), whose body text contains two
cross-references pointing at the wrong Section numbers, and whose Table of
Contents is stale in three independent ways (a wrong number, a wrong
title, a missing entry) -- and repairs all three problem classes.

Deliberately a single document, single session, no cross_session_search:
the redline-workspace build (own-folder sibling to this one) found that
cross_session_search can cause SuperDocs to silently re-open a stale
snapshot of a document already open in the current session. This build's
task doesn't need cross-session data at all, so it structurally can't hit
that bug -- two narrow, sequential same-document instructions instead,
matching the instruction style that was proven reliable there (targeted
and procedural, not open-ended).

Ground truth: the manual has exactly 10 Sections in document order.
Renumbered correctly, each Section's number must equal its position
(1st Section heading -> "SECTION 1", ..., 10th -> "SECTION 10"), because
they're already in the right order -- only the numbers are wrong. That
makes verification exact rather than approximate: the correct final state
is fully known in advance, not just "plausible."

Two real runs of the byte-identical RENUMBER_INSTRUCTION produced very
different outcomes (see PROGRESS.md): one clean pass, one run with a false
"updated all 10 sections" claim covering near-zero real progress. That's
real run-to-run non-determinism, not a wording problem -- so this version
wraps the renumber turn specifically in a verify-then-retry loop: run it
against a fresh session and a fresh copy of the source document, check the
actual resulting headings against ground truth, and if it doesn't match,
throw the attempt away and try again from scratch, up to
MAX_RENUMBER_ATTEMPTS times. Every attempt's real outcome is logged,
whether or not retrying converges to a pass -- both are real information.
The cross-reference and Table of Contents turns are left single-shot; the
non-determinism only showed up in renumbering.

Run `python build.py --dry-run` first: prints the full plan with zero API
calls. Only run for real (`python build.py`) after reading that output.
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.superdocs.app"
HERE = Path(__file__).parent
CONTENT_DIR = HERE / "content"
OUTPUT_DIR = HERE / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

MAX_RENUMBER_ATTEMPTS = 3


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------- API helpers (same shape as the redline-workspace build) ----------


class Client:
    def __init__(self, api_key: str):
        self.http = httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {api_key}"}, timeout=240.0)

    def upload_document(self, path: Path, session_id: str, open_mode: str = "replace") -> dict:
        with open(path, "rb") as f:
            resp = self.http.post(
                "/v1/documents/upload",
                files={"file": (path.name, f, "text/html")},
                data={"session_id": session_id, "open_mode": open_mode},
            )
        resp.raise_for_status()
        return resp.json()

    def start_chat(self, message: str, session_id: str, approval_mode: str = "ask_every_time") -> dict:
        resp = self.http.post(
            "/v1/chat/async",
            json={"message": message, "session_id": session_id, "approval_mode": approval_mode},
        )
        resp.raise_for_status()
        return resp.json()

    def get_job(self, job_id: str) -> dict:
        resp = self.http.get(f"/v1/jobs/{job_id}")
        resp.raise_for_status()
        return resp.json()

    def approve_all(self, session_id: str, job_id: str, pending_changes: list[dict]) -> None:
        changes = [{"change_id": c["change_id"], "approved": True} for c in pending_changes]
        resp = self.http.post(f"/v1/chat/{session_id}/approve", json={"job_id": job_id, "approved": True, "changes": changes})
        resp.raise_for_status()

    def continue_job(self, session_id: str, job_id: str) -> None:
        resp = self.http.post(f"/v1/chat/{session_id}/continue", json={"job_id": job_id, "continue": True})
        resp.raise_for_status()

    def wait_for_job(self, session_id: str, job_id: str, label: str, max_wait_s: int = 400) -> dict:
        start = time.time()
        while time.time() - start < max_wait_s:
            job = self.get_job(job_id)
            status = job["status"]
            if status == "completed":
                log(f"  {label}: completed")
                return job
            if status in ("failed", "cancelled"):
                raise RuntimeError(f"{label} job {status}: {job.get('error')}")
            if status == "awaiting_approval":
                metadata = job.get("metadata") or {}
                if metadata.get("awaiting_kind") == "continue_prompt":
                    log(f"  {label}: paused mid-edit, continuing")
                    self.continue_job(session_id, job_id)
                else:
                    pending = metadata.get("pending_changes") or []
                    log(f"  {label}: awaiting approval on {len(pending)} change(s) -- approving")
                    self.approve_all(session_id, job_id, pending)
            else:
                log(f"  {label}: {status}...")
            time.sleep(4)
        raise TimeoutError(f"{label} job did not complete in time")

    def session_documents(self, session_id: str, include_html: bool = True) -> dict:
        resp = self.http.get(f"/v1/sessions/{session_id}/documents", params={"include_html": str(include_html).lower()})
        resp.raise_for_status()
        return resp.json()

    def export_html(self, html: str, filename: str, fmt: str = "docx") -> Path:
        resp = self.http.post("/v1/documents/export", json={"html": html, "format": fmt, "options": {"filename": filename}})
        resp.raise_for_status()
        ext = {"docx": "docx", "pdf": "pdf", "html": "html"}.get(fmt, fmt)
        out_path = OUTPUT_DIR / f"{filename}.{ext}"
        if "application/json" in resp.headers.get("content-type", ""):
            data = resp.json()
            url = data.get("download_url") or data.get("url")
            out_path.write_bytes(self.http.get(url).content)
        else:
            out_path.write_bytes(resp.content)
        return out_path


def _norm(s: str) -> str:
    return re.sub(r"[_\-\s]+", " ", (s or "")).strip().lower()


def find_document_html(doc_list: dict, title_substring: str) -> str:
    needle = _norm(title_substring)
    for d in doc_list.get("documents", []):
        if needle in _norm(d.get("title")):
            html = d.get("html")
            if not html:
                raise ValueError(f"document matching '{title_substring}' found but has no html: {d}")
            return html
    raise ValueError(f"no open document matching '{title_substring}' -- got {doc_list}")


# ---------- the plan ----------

RENUMBER_INSTRUCTION = (
    "This document has ten Section headings (each one looks like 'SECTION <number> — <TITLE>'), "
    "already in the correct reading order from top to bottom, but their numbers are wrong -- some "
    "are skipped, one number is used twice, and the numbers run past ten even though there are only "
    "ten Sections. Go through the Section headings in top-to-bottom order and renumber them "
    "sequentially: the first heading becomes 'SECTION 1', the second becomes 'SECTION 2', and so on "
    "through 'SECTION 10' for the tenth and last one. Keep each heading's title text exactly as it "
    "is now -- only change the number. Do not touch the Table of Contents or any body paragraph "
    "text in this step."
)

CROSSREF_INSTRUCTION = (
    "This document's Section numbers were just corrected so they now run 1 through 10 in order. "
    "In the body text there are two sentences that reference another Section by number, written "
    "like 'Section <number> of this Manual'. For each one, work out which Section it is actually "
    "describing -- one refers to where confidentiality obligations for incident records are set "
    "out, the other refers to where termination decisions are processed -- and update its number "
    "to match that target Section's new, corrected number. Do not change anything else in the "
    "document -- not the Table of Contents, not any heading, nothing else in the body text."
)

TOC_INSTRUCTION = (
    "This document's Section numbers were just corrected so they now run 1 through 10 in order. "
    "This document has a Table of Contents near the top, listing Sections by number and title. "
    "Compare every Table of Contents entry against the Section it refers to: fix any entry whose "
    "listed number no longer matches that Section's corrected number, fix any entry whose listed "
    "title text no longer matches that Section's actual current title, and add a Table of Contents "
    "entry for any Section that doesn't have one yet, in its correct position in the list. When you "
    "are done there must be exactly ten Table of Contents entries, one per Section, in order. Do "
    "not change anything else in the document -- not any heading, not any body paragraph text."
)


def print_dry_run() -> None:
    print("=== DRY RUN -- no API calls will be made ===\n")
    print(f"Document that would be uploaded to a single session: {CONTENT_DIR / 'manual.html'}")
    print()
    print("Known-broken structure as authored:")
    print("  Section heading numbers in document order: 1, 2, 4, 5, 6, 6, 7, 9, 10, 11")
    print("  (gap at 3, duplicate 6, gap at 8, runs to 11 instead of stopping at 10)")
    print("  Body cross-ref in Section 'Incident Reporting': cites Section 9 for Confidentiality")
    print("    -> Confidentiality is the 8th heading in order, so correct final number is 8")
    print("  Body cross-ref in Section 'Disciplinary Actions': cites Section 10 for Termination")
    print("    -> Termination is the 9th heading in order, so correct final number is 9")
    print("  TOC entry for the 3rd Section: number correct (3), title stale ('Cargo Inspection")
    print("    Requirements' instead of 'Vehicle Inspection Requirements')")
    print("  TOC entry for 'Drug and Alcohol Policy': listed as Section 5 (duplicate of Incident")
    print("    Reporting's entry), correct final number is 6")
    print("  TOC: no entry at all for the 10th Section ('Miscellaneous Provisions')")
    print()
    print(f"Chat instruction 1 (renumber headings only, no document_id set), retried up to")
    print(f"{MAX_RENUMBER_ATTEMPTS} times against a fresh session + fresh document each attempt,")
    print("verified against ground truth after every attempt, since this exact instruction produced")
    print("two very different real outcomes on two identical prior runs (see PROGRESS.md):")
    print(f"  {RENUMBER_INSTRUCTION[:200]}...")
    print()
    print("Chat instruction 2 (fix the two body cross-refs against the corrected numbers, only),")
    print("single-shot, run once against whichever session's renumber attempt succeeded (or the")
    print("last attempt, if none did):")
    print(f"  {CROSSREF_INSTRUCTION[:200]}...")
    print()
    print("Chat instruction 3 (fix the Table of Contents against the corrected numbers, only),")
    print("single-shot:")
    print(f"  {TOC_INSTRUCTION[:200]}...")
    print()
    print("Split into three narrow, single-purpose turns rather than two: an earlier run bundled")
    print("the cross-ref fix and the TOC fix into one instruction, and the agent silently completed")
    print("only the cross-ref half while reporting full success -- see PROGRESS.md.")
    print()
    print("Expected final state: headings numbered 1-10 sequentially in order; both cross-refs")
    print("updated (8 and 9 respectively); TOC has 10 correct entries, no stale title, no stale")
    print("number, no missing entry.")
    print()
    print(f"API calls this would make for real: 1-{MAX_RENUMBER_ATTEMPTS} uploads + renumber turns")
    print("(1 per attempt, until one verifies correct or the cap is hit), plus 2 more chat turns")
    print("(crossref, TOC) and 1 export. No cross_session_search used anywhere.")
    print("Re-run without --dry-run once this plan looks right.")


# ---------- verification ----------

SECTION_TITLES_IN_ORDER = [
    "INTRODUCTION AND SCOPE",
    "DEFINITIONS",
    "VEHICLE INSPECTION REQUIREMENTS",
    "HOURS OF SERVICE",
    "INCIDENT REPORTING",
    "DRUG AND ALCOHOL POLICY",
    "DISCIPLINARY ACTIONS",
    "CONFIDENTIALITY",
    "TERMINATION",
    "MISCELLANEOUS PROVISIONS",
]


def verify_headings(html: str) -> dict:
    """Narrow check used by the renumber retry loop: just the heading numbers
    and titles, not cross-refs or TOC (those haven't run yet at this point)."""
    headings = re.findall(r"SECTION\s+(\d+)\s*[—\-]\s*([A-Z ,&]+?)(?:</h\d>|\n)", html)
    heading_numbers = [int(n) for n, _ in headings]
    found_titles = [t.strip().rstrip(".") for _, t in headings]
    expected_numbers = list(range(1, 11))
    numbers_correct = heading_numbers == expected_numbers
    titles_correct = len(found_titles) == 10 and all(
        SECTION_TITLES_IN_ORDER[i] in found_titles[i] for i in range(min(10, len(found_titles)))
    )
    return {
        "found_numbers": heading_numbers,
        "found_titles": found_titles,
        "numbers_correct": numbers_correct,
        "titles_correct": titles_correct,
        "correct": numbers_correct and titles_correct,
    }


def verify(html: str) -> dict:
    results = {}

    # 1. Heading sequence: every "SECTION <n> — <TITLE>" heading, in document order.
    headings = re.findall(r"SECTION\s+(\d+)\s*[—\-]\s*([A-Z ,&]+?)(?:</h\d>|\n)", html)
    heading_numbers = [int(n) for n, _ in headings]
    expected_numbers = list(range(1, 11))
    results["headings_sequential_1_to_10"] = {
        "found": heading_numbers,
        "expected": expected_numbers,
        "correct": heading_numbers == expected_numbers,
    }

    # 2. Titles still in the same order and intact (renumbering shouldn't have touched titles).
    found_titles = [t.strip().rstrip(".") for _, t in headings]
    results["titles_unchanged_and_in_order"] = {
        "found": found_titles,
        "correct": len(found_titles) == 10
        and all(SECTION_TITLES_IN_ORDER[i] in found_titles[i] for i in range(min(10, len(found_titles)))),
    }

    # 3. Cross-ref: confidentiality reference should now cite Section 8.
    m = re.search(r"confidentiality obligations[^.]*?Section\s+(\d+)", html, re.IGNORECASE | re.DOTALL)
    results["crossref_confidentiality_points_to_8"] = {
        "found": m.group(1) if m else None,
        "correct": m is not None and m.group(1) == "8",
    }

    # 4. Cross-ref: termination reference should now cite Section 9.
    m = re.search(r"processed pursuant to Section\s+(\d+)", html, re.IGNORECASE)
    results["crossref_termination_points_to_9"] = {
        "found": m.group(1) if m else None,
        "correct": m is not None and m.group(1) == "9",
    }

    # 5. TOC: entry for Section 3 has the current title, not the stale one.
    # Body headings are ALL CAPS ("SECTION 1 -- INTRODUCTION..."); TOC entries are
    # title case ("Section 1 -- Introduction..."). The boundary must be case-sensitive
    # or it matches the TOC's own first entry instead of the real heading below it.
    toc_region_match = re.search(r"TABLE OF CONTENTS(.*?)(?=SECTION 1\s*[—\-])", html, re.DOTALL)
    toc_region = toc_region_match.group(1) if toc_region_match else ""
    results["toc_section3_title_fixed"] = {
        "correct": "Vehicle Inspection Requirements" in toc_region and "Cargo Inspection" not in toc_region,
    }

    # 6. TOC: Drug and Alcohol Policy entry now says Section 6, not a duplicated Section 5.
    dup5_count = len(re.findall(r"Section\s+5\s*[—\-]", toc_region, re.IGNORECASE))
    results["toc_drug_alcohol_number_fixed"] = {
        "correct": bool(re.search(r"Section\s+6\s*[—\-]\s*Drug and Alcohol Policy", toc_region, re.IGNORECASE))
        and dup5_count == 1,
    }

    # 7. TOC: Miscellaneous Provisions entry now present.
    results["toc_missing_entry_added"] = {
        "correct": bool(re.search(r"Section\s+10\s*[—\-]\s*Miscellaneous Provisions", toc_region, re.IGNORECASE)),
    }

    # 8. TOC: exactly 10 entries total (sanity check against partial/duplicate fixes).
    toc_entry_count = len(re.findall(r"Section\s+\d+\s*[—\-]", toc_region, re.IGNORECASE))
    results["toc_has_exactly_10_entries"] = {
        "found": toc_entry_count,
        "correct": toc_entry_count == 10,
    }

    all_correct = all(r["correct"] for r in results.values())
    return {"pass": all_correct, "details": results}


# ---------- main ----------


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print_dry_run()
        return

    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key:
        print("SUPERDOCS_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    client = Client(api_key)

    # --- renumber: verify-then-retry, fresh session + fresh document each attempt ---
    attempts_log = []
    session_id = None
    for attempt in range(1, MAX_RENUMBER_ATTEMPTS + 1):
        attempt_session = f"self-heal-{uuid.uuid4()}"
        log(f"renumber attempt {attempt}/{MAX_RENUMBER_ATTEMPTS}, session: {attempt_session}")
        client.upload_document(CONTENT_DIR / "manual.html", attempt_session, open_mode="replace")
        job = client.start_chat(RENUMBER_INSTRUCTION, attempt_session, approval_mode="ask_every_time")
        client.wait_for_job(attempt_session, job["job_id"], f"renumber (attempt {attempt})")

        docs = client.session_documents(attempt_session, include_html=True)
        html = find_document_html(docs, "manual")
        check = verify_headings(html)
        attempts_log.append({"attempt": attempt, "session_id": attempt_session, **check})
        log(f"  attempt {attempt} numbers: {check['found_numbers']}  correct: {check['correct']}")

        if check["correct"]:
            session_id = attempt_session
            log(f"  attempt {attempt} verified correct, proceeding with this session")
            break
        elif attempt < MAX_RENUMBER_ATTEMPTS:
            log(f"  attempt {attempt} failed verification, discarding and retrying fresh")
        else:
            log(f"  attempt {attempt} failed verification, cap reached -- proceeding anyway with")
            log("  this session's (incorrect) result, to see how the rest of the pipeline handles it")
            session_id = attempt_session

    (OUTPUT_DIR / "renumber_attempts.json").write_text(json.dumps(attempts_log, indent=2), encoding="utf-8")
    converged = any(a["correct"] for a in attempts_log)
    log(f"renumber retry summary: {len(attempts_log)} attempt(s), converged to a correct result: {converged}")

    log("fixing cross-references")
    job = client.start_chat(CROSSREF_INSTRUCTION, session_id, approval_mode="ask_every_time")
    client.wait_for_job(session_id, job["job_id"], "crossref")

    log("fixing Table of Contents")
    job = client.start_chat(TOC_INSTRUCTION, session_id, approval_mode="ask_every_time")
    client.wait_for_job(session_id, job["job_id"], "toc")

    docs = client.session_documents(session_id, include_html=True)
    html = find_document_html(docs, "manual")

    result = verify(html)
    result["renumber_attempts"] = attempts_log
    result["renumber_converged"] = converged
    log("verification:")
    for name, detail in result["details"].items():
        log(f"  {name}: {json.dumps(detail)}")
    log(f"OVERALL: {'PASS' if result['pass'] else 'FAIL'}")

    export_path = client.export_html(html, "repaired_manual", fmt="docx")
    log(f"exported -> {export_path}")

    (OUTPUT_DIR / "final_document.html").write_text(html, encoding="utf-8")
    (OUTPUT_DIR / "verification_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    if not result["pass"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
