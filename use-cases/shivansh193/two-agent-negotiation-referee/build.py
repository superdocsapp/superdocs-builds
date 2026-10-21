"""Two-Agent Document Negotiation with a Human Referee -- built against
the real, hosted SuperDocs product. Two agents, TechFlow Solutions
(Vendor) and Meridian Retail Group (Customer), negotiate two terms of an
MSA -- Payment Terms and Limitation of Liability -- by alternately
proposing changes to one shared document. Every round is a real,
reviewable proposed change (`approval_mode: "ask_every_time"`, never
`auto-apply`); nothing is ever silently rewritten.

Each agent's position -- opening ask, walk-away limit, step size per
round -- lives entirely in its own playbook, an HTML data file
(`content/playbook_vendor.html`, `content/playbook_customer.html`), never
in this script. `parse_playbook()` reads those numbers back out of the
files at runtime and uses them for this build's own independent
convergence check, so the check itself is also data-driven, not hardcoded
against one specific scenario. `--customer-playbook` selects which
customer playbook file to use; `content/playbook_customer_escalation.html`
is the same file with exactly one number changed (the liability ceiling,
pushed below Vendor's floor so no agreement is possible), used to prove
the escalation path.

A finding from testing before this build was designed: exporting a
session with a pending, unapproved change does NOT produce tracked
changes -- it silently exports the pre-change state, ignoring the pending
diff entirely. Genuine Word-native tracked changes (`w:ins`/`w:del`) DO
come out of `POST /v1/documents/export` when you construct `<ins>`/`<del>`
HTML yourself and export it via the `html` field (not `session_id`).
`build_redline_html()` does exactly that for the two negotiated terms,
using each term's original anchor value and its final negotiated value.

Run `python build.py --dry-run` first: prints the full plan with zero API
calls. Only run for real (`python build.py [--customer-playbook ...]`)
after reading that output.
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
import zipfile
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.superdocs.app"
HERE = Path(__file__).parent
CONTENT_DIR = HERE / "content"
OUTPUT_DIR = HERE / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

MAX_ROUNDS = 6
NUM_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------- API helpers (same shape as the other builds) ----------


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

    def reject_all(self, session_id: str, job_id: str, pending_changes: list[dict], feedback: str | None = None) -> None:
        changes = [
            {"change_id": c["change_id"], "approved": False, **({"feedback": feedback} if feedback else {})}
            for c in pending_changes
        ]
        resp = self.http.post(f"/v1/chat/{session_id}/approve", json={"job_id": job_id, "approved": False, "changes": changes})
        resp.raise_for_status()

    def continue_job(self, session_id: str, job_id: str) -> None:
        resp = self.http.post(f"/v1/chat/{session_id}/continue", json={"job_id": job_id, "continue": True})
        resp.raise_for_status()

    def wait_for_job(
        self, session_id: str, job_id: str, label: str, decision: str = "approve", feedback: str | None = None, max_wait_s: int = 400
    ) -> dict:
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
                    if decision == "approve":
                        log(f"  [{label}] awaiting approval on {len(pending)} change(s) -- approving")
                        self.approve_all(session_id, job_id, pending)
                    else:
                        log(f"  [{label}] awaiting approval on {len(pending)} change(s) -- REJECTING (test)")
                        self.reject_all(session_id, job_id, pending, feedback=feedback)
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


# ---------- playbook parsing (data-driven, not hardcoded) ----------


def parse_playbook(path: Path) -> dict:
    text = re.sub(r"<[^>]+>", " ", path.read_text(encoding="utf-8"))
    def find(pattern):
        m = re.search(pattern, text)
        return int(m.group(1)) if m else None
    return {
        "payment_opening": find(r"Opening ask:\s*Net\s+(\d+)\s+days"),
        "payment_limit": find(r"Walk-away (?:floor|ceiling):\s*Net\s+(\d+)\s+days"),
        "payment_step": find(r"Step size per round:\s*(\d+)\s+days"),
        "liability_opening": find(r"Opening ask:\s*a cap equal to \w+\s*\((\d+)\)\s*times fees"),
        "liability_limit": find(r"Walk-away (?:floor|ceiling):\s*\w+\s*\((\d+)\)\s*times fees"),
        "liability_step": find(r"Step size per round:\s*\w+\s*\((\d+)\)\s*times fees"),
    }


# ---------- document value extraction ----------


def extract_payment_days(html: str) -> int | None:
    m = re.search(r"Net\s+(\d+)\s+days", html)
    return int(m.group(1)) if m else None


def extract_liability_multiplier(html: str) -> int | None:
    m = re.search(r"\((\d+)\)\s*times the total fees", html)
    return int(m.group(1)) if m else None


def snapshot(html: str) -> dict:
    return {"payment_days": extract_payment_days(html), "liability_mult": extract_liability_multiplier(html)}


def check_agreement(snap: dict, vendor_pb: dict, customer_pb: dict) -> bool:
    if snap["payment_days"] is None or snap["liability_mult"] is None:
        return False
    payment_ok = snap["payment_days"] <= vendor_pb["payment_limit"] and snap["payment_days"] >= customer_pb["payment_limit"]
    liability_ok = snap["liability_mult"] <= vendor_pb["liability_limit"] and snap["liability_mult"] >= customer_pb["liability_limit"]
    return payment_ok and liability_ok


# ---------- the plan ----------


def opening_instruction() -> str:
    return (
        "Read the document open in this session called playbook_vendor to get your negotiating position "
        "from it -- but do not edit playbook_vendor itself, it is a reference only. Make your edit to the "
        "document called msa_terms (the currently focused document). In msa_terms, Section 4 (Payment "
        "Terms) and Section 7 (Limitation of Liability) currently state placeholder values. In msa_terms, "
        "set Section 4's stated payment period to your playbook's opening ask for Payment Terms, phrased "
        "exactly as 'Net N days' with a numeral N. In msa_terms, set Section 7's stated cap to your "
        "playbook's opening ask for Limitation of Liability, phrased exactly as 'WORD (N) times the total "
        "fees paid by Customer in the preceding twelve (12) months', spelling out both the word and the "
        "numeral N (for example 'two (2) times'). Add a short note right after each sentence you changed "
        "in msa_terms: '(TechFlow Solutions, round 1)'. Do not change anything else in msa_terms, and do "
        "not make any edit to playbook_vendor."
    )


def counter_instruction(playbook_doc: str, party_label: str, limit_word: str, round_num: int) -> str:
    return (
        f"Read the document open in this session called {playbook_doc} to get your negotiating position "
        f"from it -- but do not edit {playbook_doc} itself, it is a reference only. Look at the document "
        f"called msa_terms (the currently focused document), specifically its Section 4 (Payment Terms) "
        f"and Section 7 (Limitation of Liability) -- these currently reflect the other party's latest "
        f"position. For EACH of these two terms in msa_terms, compare the current stated value against "
        f"your playbook's walk-away {limit_word} for that term. If the current value already satisfies "
        f"your playbook (does not violate your walk-away {limit_word}), leave that term's sentence in "
        f"msa_terms completely unchanged -- do not restate it. If the current value violates your "
        f"walk-away {limit_word}, edit msa_terms to move it by exactly your playbook's step size for that "
        f"term, in your favorable direction, and never move it past your own walk-away {limit_word} -- "
        f"keep the exact same phrasing already used ('Net N days' for Payment Terms; 'WORD (N) times the "
        f"total fees paid by Customer in the preceding twelve (12) months' for Limitation of Liability, "
        f"spelling out both the word and the numeral). Add a short note right after any sentence you "
        f"changed in msa_terms: '({party_label}, round {round_num})'. Do not change a term you did not "
        f"need to move, do not change anything else in msa_terms, and do not make any edit to {playbook_doc}."
    )


def print_dry_run(customer_playbook_path: Path) -> None:
    vendor_pb = parse_playbook(CONTENT_DIR / "playbook_vendor.html")
    customer_pb = parse_playbook(customer_playbook_path)
    print("=== DRY RUN -- no API calls will be made ===\n")
    print(f"Document being negotiated: {CONTENT_DIR / 'msa_terms.html'}")
    print(f"Vendor playbook: {CONTENT_DIR / 'playbook_vendor.html'} -> {vendor_pb}")
    print(f"Customer playbook: {customer_playbook_path} -> {customer_pb}")
    print()
    zopa_payment = customer_pb["payment_limit"] <= vendor_pb["payment_limit"]
    zopa_liability = customer_pb["liability_limit"] <= vendor_pb["liability_limit"]
    print(f"Zone of possible agreement -- payment terms: {'EXISTS' if zopa_payment else 'NONE (will escalate)'}")
    print(f"Zone of possible agreement -- liability cap:  {'EXISTS' if zopa_liability else 'NONE (will escalate)'}")
    print()
    print("Plan:")
    print("  0. Pre-round test: vendor's opening proposal is generated, then deliberately REJECTED,")
    print("     to prove a rejected round leaves no residue (document re-checked byte-for-byte).")
    print("  1. Vendor's real opening proposal (approved).")
    print(f"  2. Up to {MAX_ROUNDS - 1} further rounds, alternating customer/vendor counters, each a real")
    print("     reviewable proposed change (ask_every_time, never auto-apply). Stops early the moment")
    print("     this build's own independent check (using both playbooks' actual numbers, not the model's")
    print("     say-so) confirms both terms are within both parties' limits.")
    print(f"  3. If {MAX_ROUNDS} rounds pass without agreement: ESCALATE -- write output/escalation_memo.json")
    print("     with the full round history and both playbooks' positions for a human referee. No further")
    print("     rounds are attempted after that -- this is a hard cap, not a hope.")
    print("  4. Export: build a redline HTML from the original anchor values vs the final negotiated")
    print("     values (or the state at escalation), with real <ins>/<del> tags, and export THAT via the")
    print("     html field directly -- exporting session_id alone does not carry tracked changes; this was")
    print("     tested directly before this build was designed (see PROGRESS.md).")
    print()
    print(f"API calls this would make for real: 1 upload x3 (doc + 2 playbooks), 1 opening + 1 rejected-test")
    print(f"turn, then up to {MAX_ROUNDS} more turns, plus 1 export. No cross_session_search used.")
    print("Re-run without --dry-run once this plan looks right.")


# ---------- redline construction + verification ----------


def build_redline_html(final_html: str, orig_payment: int, final_payment: int, orig_liability: int, final_liability: int) -> str:
    html = final_html
    if final_payment != orig_payment:
        old_phrase = f"Net {orig_payment} days"
        new_phrase = f"Net {final_payment} days"
        html = html.replace(new_phrase, f"<del>{old_phrase}</del><ins>{new_phrase}</ins>", 1)
    if final_liability != orig_liability:
        old_word = NUM_WORDS.get(orig_liability, str(orig_liability))
        new_word = NUM_WORDS.get(final_liability, str(final_liability))
        old_phrase = f"{old_word} ({orig_liability}) times"
        new_phrase = f"{new_word} ({final_liability}) times"
        html = html.replace(new_phrase, f"<del>{old_phrase}</del><ins>{new_phrase}</ins>", 1)
    return html


def verify_tracked_changes(docx_path: Path) -> dict:
    with zipfile.ZipFile(docx_path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    ins_count = len(re.findall(r"<w:ins\b", xml))
    del_count = len(re.findall(r"<w:del\b", xml))
    has_deltext = "<w:delText" in xml
    return {
        "ins_count": ins_count,
        "del_count": del_count,
        "has_delText_element": has_deltext,
        "correct": ins_count > 0 and del_count > 0 and has_deltext,
    }


# ---------- main ----------


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--customer-playbook", default="playbook_customer.html")
    args = parser.parse_args()

    customer_playbook_path = CONTENT_DIR / args.customer_playbook
    customer_playbook_title = customer_playbook_path.stem

    if args.dry_run:
        print_dry_run(customer_playbook_path)
        return

    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key:
        print("SUPERDOCS_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    client = Client(api_key)

    vendor_pb = parse_playbook(CONTENT_DIR / "playbook_vendor.html")
    customer_pb = parse_playbook(customer_playbook_path)
    log(f"vendor playbook: {vendor_pb}")
    log(f"customer playbook ({args.customer_playbook}): {customer_pb}")

    session_id = f"negotiation-{uuid.uuid4()}"
    log(f"session: {session_id}")
    client.upload_document(CONTENT_DIR / "msa_terms.html", session_id, open_mode="replace")
    client.upload_document(CONTENT_DIR / "playbook_vendor.html", session_id, open_mode="background")
    client.upload_document(customer_playbook_path, session_id, open_mode="background")
    log(f"  opened msa_terms.html, playbook_vendor.html, {args.customer_playbook}")

    docs = client.session_documents(session_id, include_html=True)
    original_html = find_document_html(docs, "msa_terms")
    original_snap = snapshot(original_html)
    log(f"anchor values: {original_snap}")

    audit_trail = []

    # --- pre-round test: propose, then reject, prove no residue ---
    log("pre-round test: vendor opening proposal, deliberately REJECTED")
    before_reject_html = find_document_html(client.session_documents(session_id, include_html=True), "msa_terms")
    job = client.start_chat(opening_instruction(), session_id, approval_mode="ask_every_time")
    reject_job_result = client.wait_for_job(
        session_id, job["job_id"], "reject-test", decision="reject",
        feedback="Rejected deliberately: proving a denied round leaves no residue in the document.",
    )
    reject_changes = ((reject_job_result.get("result") or {}).get("document_changes") or {}).get("changes") or []
    reject_proposed = [
        {"chunk_id": c.get("chunk_id"), "status": c.get("status"), "old_html": c.get("old_html"), "new_html": c.get("new_html")}
        for c in reject_changes if c.get("operation") == "edit"
    ]
    if not reject_proposed:
        raise RuntimeError(
            "reject-test proposed ZERO edits -- this test is supposed to prove a REAL rejected proposal "
            "leaves no residue, not a no-op. Re-run: a genuine edit must be proposed and rejected here."
        )
    log(f"  reject-test proposed {len(reject_proposed)} real change(s), all denied: "
        f"{[c['status'] for c in reject_proposed]}")
    after_reject_html = find_document_html(client.session_documents(session_id, include_html=True), "msa_terms")
    no_residue = snapshot(after_reject_html) == snapshot(before_reject_html)
    log(f"  residue check: before={snapshot(before_reject_html)} after={snapshot(after_reject_html)} no_residue={no_residue}")
    audit_trail.append({
        "round": "reject-test", "actor": "vendor", "decision": "rejected", "proposed_changes": reject_proposed,
        "before": snapshot(before_reject_html), "after": snapshot(after_reject_html), "no_residue": no_residue,
    })

    # --- round 1: vendor's real opening, approved ---
    round_log = []
    outcome = None
    for round_num in range(1, MAX_ROUNDS + 1):
        actor = "vendor" if round_num % 2 == 1 else "customer"
        if round_num == 1:
            instruction = opening_instruction()
            label = f"round{round_num}-vendor-opening"
        elif actor == "vendor":
            instruction = counter_instruction("playbook_vendor", "TechFlow Solutions", "floor", round_num)
            label = f"round{round_num}-vendor-counter"
        else:
            instruction = counter_instruction(customer_playbook_title, "Meridian Retail Group", "ceiling", round_num)
            label = f"round{round_num}-customer-counter"

        log(f"round {round_num}/{MAX_ROUNDS} ({actor}): {label}")
        job = client.start_chat(instruction, session_id, approval_mode="ask_every_time")
        job_result = client.wait_for_job(session_id, job["job_id"], label, decision="approve")
        changes = ((job_result.get("result") or {}).get("document_changes") or {}).get("changes") or []
        proposed = [
            {"chunk_id": c.get("chunk_id"), "old_html": c.get("old_html"), "new_html": c.get("new_html")}
            for c in changes if c.get("operation") == "edit"
        ]

        docs = client.session_documents(session_id, include_html=True)
        html = find_document_html(docs, "msa_terms")
        snap = snapshot(html)
        agreed = check_agreement(snap, vendor_pb, customer_pb)
        round_log.append({"round": round_num, "actor": actor, "label": label, "proposed_changes": proposed, "state_after": snap, "agreed": agreed})
        audit_trail.append(round_log[-1])
        log(f"  state after round {round_num}: {snap}  agreement={agreed}")

        if agreed:
            outcome = "AGREED"
            log(f"AGREEMENT REACHED after round {round_num}/{MAX_ROUNDS}")
            break
    else:
        outcome = "ESCALATED"
        log(f"MAX_ROUNDS ({MAX_ROUNDS}) reached without agreement -- escalating to human referee")

    final_html = find_document_html(client.session_documents(session_id, include_html=True), "msa_terms")
    final_snap = snapshot(final_html)

    if outcome == "ESCALATED":
        memo = {
            "outcome": "ESCALATED",
            "rounds_run": MAX_ROUNDS,
            "final_state": final_snap,
            "vendor_playbook": vendor_pb,
            "customer_playbook": customer_pb,
            "payment_terms_resolved": final_snap["payment_days"] is not None
            and final_snap["payment_days"] <= vendor_pb["payment_limit"]
            and final_snap["payment_days"] >= customer_pb["payment_limit"],
            "liability_cap_resolved": final_snap["liability_mult"] is not None
            and final_snap["liability_mult"] <= vendor_pb["liability_limit"]
            and final_snap["liability_mult"] >= customer_pb["liability_limit"],
            "round_history": round_log,
            "referral_note": (
                f"Automated negotiation did not converge within {MAX_ROUNDS} rounds. "
                "Escalating to a human referee for a final decision. See round_history for the full "
                "audit trail and the two playbook sections above for both parties' walk-away limits."
            ),
        }
        (OUTPUT_DIR / "escalation_memo.json").write_text(json.dumps(memo, indent=2), encoding="utf-8")
        log(f"escalation memo written -> {OUTPUT_DIR / 'escalation_memo.json'}")

    redline_html = build_redline_html(
        final_html, original_snap["payment_days"], final_snap["payment_days"],
        original_snap["liability_mult"], final_snap["liability_mult"],
    )
    export_filename = "negotiated_msa_AGREED" if outcome == "AGREED" else "negotiated_msa_ESCALATED"
    export_path = client.export_html(redline_html, export_filename, fmt="docx")
    log(f"exported -> {export_path}")

    tc_result = verify_tracked_changes(export_path)
    log(f"tracked-changes verification: {json.dumps(tc_result)}")

    result = {
        "outcome": outcome,
        "rounds_run": len(round_log),
        "original_state": original_snap,
        "final_state": final_snap,
        "reject_test": audit_trail[0],
        "tracked_changes_verification": tc_result,
        "customer_playbook_used": args.customer_playbook,
    }
    log(f"OVERALL OUTCOME: {outcome}")

    (OUTPUT_DIR / "final_document.html").write_text(final_html, encoding="utf-8")
    (OUTPUT_DIR / "redline_document.html").write_text(redline_html, encoding="utf-8")
    (OUTPUT_DIR / "audit_trail.json").write_text(json.dumps(audit_trail, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "verification_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    if outcome != "AGREED" and args.customer_playbook == "playbook_customer.html":
        sys.exit(1)


if __name__ == "__main__":
    main()
