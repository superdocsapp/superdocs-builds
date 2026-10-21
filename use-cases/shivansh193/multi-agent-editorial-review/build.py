"""Multi-Agent Editorial Review Loop -- built against the real, hosted
SuperDocs product. A writer agent expands a bullet-point outline into a
full first draft; a fact-checker agent and a style-reviewer agent then
work the same document, on two genuinely disjoint sets of sections, and
are fired as real concurrent API calls rather than sequential turns.

Two things this build is specifically built to prove, not just assert:

1. No section collisions. The fact-checker's target sections (Market
   Analysis, Risk Assessment) and the style-reviewer's target sections
   (Executive Summary, Technical Specifications) are disjoint by
   construction. Both turns' *submissions* are fired at the same instant
   (a ThreadPoolExecutor, not a sequential loop), genuinely racing to
   start on the same session. The first real run found that SuperDocs
   itself prevents the race: `POST /v1/chat/async` returns 409 Conflict
   outright when a chat request lands on a session that already has
   another chat job active, rather than accepting both and risking a
   collision. That's a stronger answer than what this build originally
   set out to test empirically -- collisions aren't just absent, they're
   structurally prevented by the API rejecting concurrent submissions.
   `run_turn` retries on 409 with backoff, which is what "two agents
   racing to edit one document" has to do against this API in practice.
   Verification still checks all four planted issues after every round,
   so a real collision (if the platform's serialization ever had a gap)
   would still show up as exactly one side's fixes missing.

2. Provable loop termination. The review loop is a plain `for` loop over
   `range(1, MAX_ROUNDS + 1)` with an early `break` on convergence -- it
   terminates in at most MAX_ROUNDS iterations by construction, whether
   or not the agents ever agree the document is clean. Not a sophisticated
   proof, but a real and correct one: a bounded for-loop cannot run
   forever.

Ground truth: two deliberately wrong figures (a market-size number and a
competitor market-share number) that only the fact-checker, reading the
verified_facts document, can correct; and two deliberate style violations
(an over-length Executive Summary, one passive-voice sentence) that only
the style-reviewer, reading the style_guardrails document, can fix. Two
further guardrails in that same document are already satisfied by the
draft and must NOT get spuriously "fixed" -- getting that split right is
part of what's verified.

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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.superdocs.app"
HERE = Path(__file__).parent
CONTENT_DIR = HERE / "content"
OUTPUT_DIR = HERE / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

MAX_ROUNDS = 2


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------- API helpers (same shape as the other two builds) ----------


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
                log(f"  [{label}] completed")
                return job
            if status in ("failed", "cancelled"):
                raise RuntimeError(f"{label} job {status}: {job.get('error')}")
            if status == "awaiting_approval":
                metadata = job.get("metadata") or {}
                if metadata.get("awaiting_kind") == "continue_prompt":
                    log(f"  [{label}] paused mid-edit, continuing")
                    self.continue_job(session_id, job_id)
                else:
                    pending = metadata.get("pending_changes") or []
                    log(f"  [{label}] awaiting approval on {len(pending)} change(s) -- approving")
                    self.approve_all(session_id, job_id, pending)
            else:
                log(f"  [{label}] {status}...")
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


MAX_409_RETRIES = 40
RETRY_409_INTERVAL_S = 5


def run_turn(client: Client, session_id: str, label: str, instruction: str) -> int:
    """Returns how many 409s this turn hit before its start_chat call was
    accepted -- the platform rejects a chat request outright with 409
    Conflict while another chat job is already active on the same
    session, rather than risking a race between them. Discovered on the
    first real run of this build: retry-with-backoff on 409 turns that
    rejection into "wait your turn," which is the only way two turns
    submitted at the same instant against one session can both land."""
    log(f"[{label}] starting")
    conflicts = 0
    while True:
        try:
            job = client.start_chat(instruction, session_id, approval_mode="ask_every_time")
            break
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409 and conflicts < MAX_409_RETRIES:
                conflicts += 1
                log(f"  [{label}] 409 Conflict (session busy with another chat job) -- "
                    f"retrying in {RETRY_409_INTERVAL_S}s (attempt {conflicts}/{MAX_409_RETRIES})")
                time.sleep(RETRY_409_INTERVAL_S)
                continue
            raise
    client.wait_for_job(session_id, job["job_id"], label)
    return conflicts


def run_concurrent_turns(client: Client, session_id: str, turns: list[tuple[str, str]]) -> dict[str, int]:
    """Fires every (label, instruction) turn's *submission* at the same
    instant (a ThreadPoolExecutor, not a sequential loop) so they're
    genuinely racing to start on the same session. Whichever one the
    platform rejects with 409 retries until the other's job frees the
    session. Returns each label's 409 count -- the real evidence of
    whether/how much contention actually happened."""
    with ThreadPoolExecutor(max_workers=len(turns)) as ex:
        futures = {label: ex.submit(run_turn, client, session_id, label, instruction) for label, instruction in turns}
        return {label: f.result() for label, f in futures.items()}


# ---------- the plan ----------

WRITER_INSTRUCTION = (
    "Expand each section's bullet list into 2-3 full prose sentences per section. Keep every fact, name, "
    "and number exactly as stated in the bullets -- do not invent, add, or change any fact, and do not "
    "soften or qualify any number. Keep each section's heading exactly as it is now. Do not add new "
    "sections and do not remove any existing bullet's content, just turn it into prose."
)

FACT_CHECK_INSTRUCTION = (
    "There is another document open in this session called verified_facts. Read it specifically. Check "
    "exactly two claims in THIS document against it: the total addressable market figure in the Market "
    "Analysis section, and HearthLink's market share figure in the Risk Assessment section. For each claim "
    "that doesn't match verified_facts, correct the number in THIS document to match verified_facts "
    "exactly, and add a short parenthetical note right after the corrected number: '(fact-checked against "
    "verified_facts)'. If a claim already matches verified_facts, leave it untouched. Do not change "
    "anything else in the document -- not the Executive Summary section, not the Technical Specifications "
    "section, and no other sentence in Market Analysis or Risk Assessment beyond the one figure in each."
)

REVIEW_INSTRUCTION = (
    "There is another document open in this session called style_guardrails. Read it specifically. Check "
    "THIS document's Executive Summary section against guardrail 1 (must be 80 words or fewer) and THIS "
    "document's Technical Specifications section against guardrail 2 (no passive voice -- every sentence "
    "must have an explicit, active-voice subject performing the action). If the Executive Summary is "
    "longer than 80 words, rewrite it to 80 words or fewer while keeping all three of its factual points, "
    "and add a short parenthetical note at the end of the section: '(style-reviewed: trimmed for length)'. "
    "If any sentence in Technical Specifications uses passive voice, rewrite that sentence in active voice, "
    "and add a short parenthetical note right after it: '(style-reviewed: active voice)'. Do not change "
    "anything else in the document -- not the Market Analysis section, not the Risk Assessment section, "
    "and no other sentence in Executive Summary or Technical Specifications beyond what these two "
    "guardrails require."
)


def print_dry_run() -> None:
    print("=== DRY RUN -- no API calls will be made ===\n")
    print(f"Document that would be uploaded to a single session: {CONTENT_DIR / 'brief_outline.html'}")
    print(f"Background documents: {CONTENT_DIR / 'verified_facts.html'}, {CONTENT_DIR / 'style_guardrails.html'}")
    print()
    print("Planted issues (ground truth):")
    print("  FACT   : Market Analysis states TAM = $4.2B -- verified_facts says $2.8B")
    print("  FACT   : Risk Assessment states HearthLink share = 61% -- verified_facts says 38%")
    print("  STYLE  : Executive Summary will draft to >80 words -- guardrail caps it at 80")
    print("  STYLE  : Technical Specifications has one passive-voice sentence -- guardrail bans it")
    print("  ALREADY OK, must NOT be touched: Risk Assessment mitigations (guardrail 3), Market")
    print("                    Analysis figures are already specific numbers, just wrong ones (guardrail 4)")
    print()
    print("Chat instruction 1 (writer, expands bullets to prose, no document_id set):")
    print(f"  {WRITER_INSTRUCTION[:200]}...")
    print()
    print(f"Then up to {MAX_ROUNDS} review round(s). Each round fires both instructions' submissions at the")
    print("same instant (ThreadPoolExecutor, not sequential) against disjoint sections. SuperDocs itself")
    print("rejects the second submission with 409 Conflict while the first is still active on that")
    print("session -- run_turn retries on 409 with backoff. Checks convergence after each round, stops")
    print("early if all four planted issues are resolved:")
    print(f"  fact-check  (targets Market Analysis, Risk Assessment): {FACT_CHECK_INSTRUCTION[:120]}...")
    print(f"  style-review (targets Exec Summary, Tech Specs):        {REVIEW_INSTRUCTION[:120]}...")
    print()
    print("Loop termination: a plain `for round in range(1, MAX_ROUNDS + 1)` with an early `break` on")
    print("convergence -- bounded by construction, terminates in at most MAX_ROUNDS rounds regardless.")
    print()
    print(f"API calls this would make for real: 1 upload + 1 writer turn, then 2 turns per round")
    print(f"(up to {MAX_ROUNDS} rounds), plus 1 export. No cross_session_search used.")
    print("Re-run without --dry-run once this plan looks right.")


# ---------- verification ----------


def verify_issues(html: str) -> dict:
    results = {}

    tam_fixed = "$2.8B" in html or "2.8B" in html
    tam_stale = "$4.2B" in html or "4.2B" in html
    results["tam_corrected"] = {"correct": tam_fixed and not tam_stale}

    share_fixed = bool(re.search(r"38%", html))
    share_stale = bool(re.search(r"61%", html))
    results["competitor_share_corrected"] = {"correct": share_fixed and not share_stale}

    exec_summary_match = re.search(r"Executive Summary(.*?)(?=<h2)", html, re.DOTALL)
    exec_text = re.sub(r"<[^>]+>", " ", exec_summary_match.group(1)) if exec_summary_match else ""
    exec_word_count = len(exec_text.split())
    results["exec_summary_length"] = {"word_count": exec_word_count, "correct": exec_word_count <= 80}

    tech_specs_match = re.search(r"Technical Specifications(.*?)(?=<h2)", html, re.DOTALL)
    tech_text = tech_specs_match.group(1) if tech_specs_match else ""
    passive_gone = "are pushed by" not in tech_text.lower()
    results["passive_voice_fixed"] = {"correct": passive_gone}

    # Guardrails already satisfied -- must not have been spuriously "fixed" or touched.
    risk_match = re.search(r"Risk Assessment(.*?)(?=<h2|\Z)", html, re.DOTALL)
    risk_text = risk_match.group(1) if risk_match else ""
    # Stem match, not just the noun "Mitigation" -- a legitimate rewrite can turn
    # "Mitigation: we will X" into "To mitigate this, we will X" without losing the
    # actual mitigation content, and the noun-only regex was blind to that form.
    mitigation_count = len(re.findall(r"[Mm]itigat", risk_text))
    results["risk_mitigations_untouched"] = {"count": mitigation_count, "correct": mitigation_count >= 2}

    all_resolved = all(r["correct"] for r in results.values())
    return {"all_resolved": all_resolved, "details": results}


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

    session_id = f"editorial-{uuid.uuid4()}"
    log(f"session: {session_id}")
    for name, mode in [
        ("brief_outline.html", "replace"),
        ("verified_facts.html", "background"),
        ("style_guardrails.html", "background"),
    ]:
        client.upload_document(CONTENT_DIR / name, session_id, open_mode=mode)
        log(f"  opened {name} ({mode})")

    log("writer: expanding outline to prose")
    run_turn(client, session_id, "writer", WRITER_INSTRUCTION)

    round_log = []
    for round_num in range(1, MAX_ROUNDS + 1):
        log(f"round {round_num}/{MAX_ROUNDS}: firing fact-check and style-review concurrently")
        conflicts = run_concurrent_turns(
            client,
            session_id,
            [("fact-check", FACT_CHECK_INSTRUCTION), ("style-review", REVIEW_INSTRUCTION)],
        )
        log(f"  round {round_num} 409 conflicts encountered: {conflicts}")
        docs = client.session_documents(session_id, include_html=True)
        html = find_document_html(docs, "brief_outline")
        check = verify_issues(html)
        round_log.append({"round": round_num, "conflicts_409": conflicts, **check})
        log(f"  round {round_num} result: {json.dumps(check['details'])}")
        if check["all_resolved"]:
            log(f"  converged after round {round_num}/{MAX_ROUNDS}, stopping")
            break
    else:
        log(f"  did not converge within {MAX_ROUNDS} rounds -- stopping anyway (hard cap reached)")

    (OUTPUT_DIR / "round_log.json").write_text(json.dumps(round_log, indent=2), encoding="utf-8")

    docs = client.session_documents(session_id, include_html=True)
    html = find_document_html(docs, "brief_outline")
    result = verify_issues(html)
    result["rounds_run"] = len(round_log)
    log("final verification:")
    for name, detail in result["details"].items():
        log(f"  {name}: {json.dumps(detail)}")
    log(f"OVERALL: {'PASS' if result['all_resolved'] else 'FAIL'} ({result['rounds_run']} round(s) run)")

    export_path = client.export_html(html, "reviewed_launch_brief", fmt="docx")
    log(f"exported -> {export_path}")

    (OUTPUT_DIR / "final_document.html").write_text(html, encoding="utf-8")
    (OUTPUT_DIR / "verification_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    if not result["all_resolved"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
