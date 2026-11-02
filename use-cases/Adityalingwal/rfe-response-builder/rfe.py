"""RFE response builder — one entry point.

Usage:
  python rfe.py check                    is the API key valid? (free)
  python rfe.py preview [case_dir]      parse + locate + checklist, offline (free)
  python rfe.py judge [case_dir]        AI coverage judgement (billable;
                                        observed: the judge question was
                                        not billed)
  python rfe.py draft [case_dir]        judge + upload + AI draft, then stop
                                        for human review (billable; observed:
                                        a full run billed 1 operation)
  python rfe.py decide approve|reject   apply the human decision, export,
                                        verify (applying and exporting are
                                        free; a feedback round that makes
                                        the model redraft may bill — see
                                        the Billing tab)

A case_dir holds two folders: notice/ (the officer's letter, exactly one
file) and petition/ (the original petition documents). Default: ./data
Supported formats: .md .txt .pdf .docx

Actual charges appear in the SuperDocs Billing tab; ops_spent here is a
cap counter, not a bill.

The same five operations are exposed as MCP tools by mcp_server.py — both
doors call the core functions in this file; there is no second
implementation.
"""
import json
import re
import sys
import time
import uuid
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.citations_from_export import (
    cited_sections_from_export,
    missing_citation_failures,
)
from engine.coverage_checklist import build_checklist
from engine.draft_instruction import build_draft_instruction
from engine.judge_coverage import (
    build_judge_instruction,
    judged_checklist,
    parse_judge_reply,
)
from engine.load_corpus import (
    notice_file,
    petition_sections,
    read_petition,
    supported_files,
    unsupported_files,
)
from engine.model import ChecklistRow, Coverage
from engine.read_document import read_document
from engine.requests_from_notice import parse_notice
from engine.response_skeleton import build_skeleton
from engine.retrieve_petition_material import load_retrieval_config, retrieve
from engine.verify_citations import find_citation_failures
from engine.verify_export import verify_export
from superdocs.client import (
    OperationBudget,
    SuperDocsClient,
    TERMINAL_JOB_STATUSES,
    read_env,
)
from superdocs.errors import SuperDocsError

MODEL_TIER = "core"
DEAD_JOB_STATUSES = TERMINAL_JOB_STATUSES - {"completed"}
MAX_JOB_WAIT_SECONDS = 420
ATTACHMENT_WAIT_SECONDS = 90
OUT = ROOT / "output"
STATE_FILE = OUT / "run_state.json"
REVIEW_OLD_TEXT_CHARS = 2000
REVIEW_NEW_TEXT_CHARS = 4000
CUT_SHORT_MARKER = "[cut short here — read the full text in pending_changes.json]"

COVERAGE_LABEL = {
    Coverage.ANSWERED: "Answered — petition material found",
    Coverage.PARTIAL: "Partially — new evidence needed",
    Coverage.NOT_PROVIDED: "Not provided — needs attorney confirmation",
}


def load_case(case_dir: Path):
    path = notice_file(case_dir / "notice")
    requests = parse_notice(read_document(path), source_name=path.name)
    petition = read_petition(case_dir / "petition")
    config = load_retrieval_config(ROOT / "config" / "retrieval.json")
    matches = retrieve(requests, petition_sections(petition), config)
    return requests, petition, config, matches, unsupported_files(case_dir / "petition")


def skipped_files_note(skipped: list[str]) -> str:
    """One line naming the petition files no reader here can open.

    A format we cannot read is not a reason to refuse the whole case — but
    the attorney has to know which documents the answer was built without.
    """
    return (
        f"skipped, format not supported: {', '.join(skipped)} — save them as "
        f".docx or .pdf and run again to include them"
    )


def make_client() -> SuperDocsClient:
    env = read_env(ROOT / ".env")
    return SuperDocsClient(
        env.get("SUPERDOCS_API_KEY", ""),
        OperationBudget(int(env.get("MAX_OPS_PER_RUN", "10"))),
    )


def judged_or_lexical_checklist(client, requests, matches, config, session_id, notes):
    lexical = build_checklist(requests, matches, config)
    try:
        reply = client.ask(
            session_id, build_judge_instruction(requests, matches), MODEL_TIER
        )
        judged = judged_checklist(requests, matches, parse_judge_reply(reply, requests))
        notes.append("coverage judged by the model")
        return judged
    except (SuperDocsError, ValueError) as e:
        # a judging failure downgrades the run, never kills it
        notes.append(f"coverage judge unavailable — using the locator's buckets ({e})")
        return lexical


def wait_for_attachments(client, session_id: str, notes, max_wait_seconds: int = ATTACHMENT_WAIT_SECONDS) -> None:
    waited = 0
    while waited < max_wait_seconds:
        status = client.attachment_status(session_id)
        # processing_jobs keeps finished history; the live counters decide
        if status.get("total_ready", 0) > 0 and status.get("total_processing", 0) == 0:
            notes.append(f"attachments processed: {status['total_ready']}")
            return
        time.sleep(3)
        waited += 3
    # attachments are an enrichment; a slow processing queue must not
    # block the draft, the excerpts in the skeleton still carry the run
    notes.append("attachments still processing — continuing; the skeleton's excerpts carry the draft")


PLACEHOLDER_REQUEST = re.compile(r"\[DRAFT RESPONSE FOR (R\d+)")


def html_to_text(html: str) -> str:
    """The review file is for the attorney; the chunk-id markup the API
    wraps a change in is not. Tags out, entities decoded — the raw HTML
    stays word-for-word in pending_changes.json."""
    text = re.sub(r"</(?:p|div|li|h[1-6]|tr)>", "\n", html)
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def quoted_block(label: str, html: str, limit: int) -> list[str]:
    # a reviewer who cannot see that the text stops early may approve a change
    # on half of it; the full string is always in pending_changes.json
    text = html_to_text(html)
    block = [f"**{label}:**", ""]
    block += [f"> {line}" if line else ">" for line in text[:limit].splitlines()]
    if len(text) > limit:
        block.append(CUT_SHORT_MARKER)
    return block


def change_heading(index: int, change: dict) -> str:
    """Name the change by the request it belongs to, when the change itself
    says so — the placeholder carries the request id. A re-proposal's old
    text is prose, not a placeholder; then the change stays unlabelled
    rather than guessed. A non-edit operation is said out loud: a deletion
    must never look like one more edit."""
    heading = f"## Change {index}"
    operation = change.get("operation", "edit")
    if operation != "edit":
        heading += f" — {operation}"
    placeholder = PLACEHOLDER_REQUEST.search(str(change.get("old_html", "")))
    if placeholder:
        heading += f" — Response to Request {placeholder.group(1)}"
    return heading


def dump_pending_changes(job: dict) -> int:
    pending = (job.get("metadata") or {}).get("pending_changes") or []
    (OUT / "pending_changes.json").write_text(
        json.dumps(pending, indent=2), encoding="utf-8"
    )
    lines = [
        "# Proposed changes awaiting review",
        "",
        "Text only — the raw form of every change, with its change_id, is in",
        "`pending_changes.json`.",
        "",
    ]
    for i, change in enumerate(pending, 1):
        lines.append(change_heading(i, change))
        explanation = (change.get("ai_explanation") or "").strip()
        # the model often restates its own text as the "explanation";
        # a duplicate teaches the reviewer nothing
        if explanation and not html_to_text(
            str(change.get("new_html", ""))
        ).startswith(explanation.rstrip("…").rstrip()):
            lines.append(f"- model's explanation: {explanation}")
        lines.append("")
        lines += quoted_block("Old", str(change.get("old_html", "")), REVIEW_OLD_TEXT_CHARS)
        lines.append("")
        lines += quoted_block("New", str(change.get("new_html", "")), REVIEW_NEW_TEXT_CHARS)
        lines.append("")
    (OUT / "pending_changes.md").write_text("\n".join(lines), encoding="utf-8")
    return len(pending)


def checklist_rows(checklist) -> list[dict]:
    return [
        {
            "request_id": row.request_id,
            "title": row.title,
            "coverage": row.coverage.value,
            "reason": row.reason,
            "matches": [
                {"file": m.file, "heading": m.heading, "score": m.score}
                for m in row.matches
            ],
        }
        for row in checklist
    ]


def note_remaining(client: SuperDocsClient, notes: list[str]) -> None:
    # the server's own count, unlike our floor-of-one estimate, is the truth
    if client.budget.remaining is not None:
        notes.append(
            f"SuperDocs reports {client.budget.remaining} operation(s) left"
        )


def carry_spent(client: SuperDocsClient, state: dict) -> None:
    """Pick the run's count up from where the last command left it.

    A state file written before the count was saved carries no figure;
    that reads as zero, never as a refusal to continue the run.
    """
    client.budget.spent = int(state.get("ops_spent", 0))


def save_spent(client: SuperDocsClient, state: dict) -> None:
    state["ops_spent"] = client.budget.spent
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def decided_elsewhere_detail(job: dict) -> str:
    """The server's own closing line for a job decided without us — e.g.
    '0 change(s) applied · 5 change(s) expired unapproved' — so the user
    sees why the export may come back unwritten."""
    responses = (job.get("metadata") or {}).get("intermediate_responses") or []
    for response in reversed(responses):
        content = response.get("content") if isinstance(response, dict) else None
        # the closing line is prose ("Successfully updated all 5 sections",
        # "5 change(s) expired unapproved"); the JSON entries beside it are
        # bookkeeping, not a message for a person
        if isinstance(content, str) and content.strip() and not content.lstrip().startswith("{"):
            return f" — SuperDocs says: {content.strip()}"
    return ""


def saved_checklist(state: dict, requests: list) -> list[ChecklistRow]:
    rows = state.get("checklist")
    if rows is None:
        raise ValueError(
            "this run's state carries no coverage checklist — it was written "
            "by an older version of the tool; delete output/run_state.json "
            "and draft again (a fresh draft bills again)"
        )
    titles = {request.id: request.title for request in requests}
    return [
        ChecklistRow(
            request_id=row["id"],
            title=titles.get(row["id"], ""),
            coverage=Coverage(row["coverage"]),
            reason=row["reason"],
        )
        for row in rows
    ]


def check_core() -> dict:
    client = make_client()
    payload = client.verify_key()
    return {"key_valid": True, "sessions": len(payload.get("sessions", []))}


def preview_core(case_dir: Path) -> dict:
    requests, petition, config, matches, skipped = load_case(case_dir)
    checklist = build_checklist(requests, matches, config)
    OUT.mkdir(exist_ok=True)
    lines = ["# Coverage checklist (offline preview — locator only)", ""]
    lines.append(f"Notice requests found: {len(requests)}")
    if skipped:
        lines.append("")
        lines.append(skipped_files_note(skipped))
    lines.append("")
    for row in checklist:
        lines.append(f"## {row.request_id} — {row.title}")
        lines.append(f"**{COVERAGE_LABEL[row.coverage]}**")
        lines.append(row.reason)
        for m in row.matches:
            lines.append(f"- {m.file} / '{m.heading}' (score {m.score})")
        lines.append("")
    checklist_file = OUT / "checklist.md"
    checklist_file.write_text("\n".join(lines), encoding="utf-8")
    return {
        "requests": len(requests),
        "checklist": checklist_rows(checklist),
        "checklist_file": str(checklist_file),
        "skipped_files": skipped,
    }


def judge_core(case_dir: Path) -> dict:
    requests, petition, config, matches, skipped = load_case(case_dir)
    client = make_client()
    lexical = build_checklist(requests, matches, config)
    reply = client.ask(
        f"rfe-judge-{uuid.uuid4().hex[:12]}",
        build_judge_instruction(requests, matches),
        MODEL_TIER,
    )
    judged = judged_checklist(requests, matches, parse_judge_reply(reply, requests))
    return {
        "case": case_dir.name,
        "ops_spent": client.budget.spent,
        "skipped_files": skipped,
        "rows": [
            {
                "request_id": judged_row.request_id,
                "locator": lex_row.coverage.value,
                "judge": judged_row.coverage.value,
                "reason": judged_row.reason,
            }
            for lex_row, judged_row in zip(lexical, judged)
        ],
    }


def draft_core(case_dir: Path) -> dict:
    OUT.mkdir(exist_ok=True)
    notes: list[str] = []
    client = make_client()

    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        pending_case = Path(state.get("case_dir", case_dir))
        if pending_case.resolve() != case_dir.resolve():
            # resuming here would silently draft the other case's job and
            # report it under this case's name
            raise ValueError(
                f"a run for '{pending_case.name}' is still pending "
                f"(job {state['job_id']}) — decide its pending changes first "
                f"(approve or reject), then draft '{case_dir.name}' fresh"
            )
        # a resumed run never reaches load_case, but the attorney still has to
        # be told which petition documents the draft was built without
        skipped = unsupported_files(case_dir / "petition")
        if skipped:
            notes.append(skipped_files_note(skipped))
        carry_spent(client, state)
        notes.append(f"resuming existing job {state['job_id']} — not paying again")
    else:
        # a case folder's name can carry spaces and punctuation that do not
        # belong in a URL path; the id the run is resumed by lives in
        # run_state.json, so it never has to be reconstructed from the name
        session_id = f"rfe-run-{uuid.uuid4().hex[:12]}"
        requests, petition, config, matches, skipped = load_case(case_dir)
        if skipped:
            notes.append(skipped_files_note(skipped))
        checklist = judged_or_lexical_checklist(
            client, requests, matches, config, f"{session_id}-judge", notes
        )
        skeleton = build_skeleton(requests, checklist)
        (OUT / "skeleton.md").write_text(skeleton, encoding="utf-8")

        client.upload_document("draft-rfe-response.md", skeleton, session_id)
        notes.append(f"uploaded skeleton to session {session_id}")

        # the original petition documents ride along as attachments, so the
        # drafting model can search the full sources, not only our excerpts —
        # exactly the files the engine read, never one it had to skip
        attachments = supported_files(case_dir / "petition")
        for source in attachments:
            client.upload_attachment(source.name, source.read_bytes(), session_id)
        notes.append(f"attached {len(attachments)} petition document(s)")
        wait_for_attachments(client, session_id, notes)

        answer = client.send_edit_instruction(
            session_id, build_draft_instruction(), MODEL_TIER
        )
        job_id = answer.get("job_id")
        if not job_id:
            raise ValueError(
                f"chat/async answered without a job_id — fields: {sorted(answer.keys())}"
            )
        state = {
            "session_id": session_id,
            "job_id": job_id,
            "case_dir": str(case_dir),
            # the buckets the document was actually built from; decide time
            # must verify against these, not against a second, judge-less
            # rebuild that would disagree with the skeleton
            "checklist": [
                {
                    "id": row.request_id,
                    "coverage": row.coverage.value,
                    "reason": row.reason,
                }
                for row in checklist
            ],
        }
        save_spent(client, state)
        notes.append(f"draft requested — job {job_id}")

    job = client.wait_for_decision_or_end(state["job_id"], MAX_JOB_WAIT_SECONDS)
    status = job.get("status")
    note_remaining(client, notes)
    result = {
        "status": status,
        "job_id": state["job_id"],
        "ops_spent": client.budget.spent,
        "skipped_files": skipped,
        "notes": notes,
    }
    if status == "awaiting_approval":
        count = dump_pending_changes(job)
        result["pending_changes"] = count
        result["pending_changes_file"] = str(OUT / "pending_changes.md")
        result["next_step"] = (
            "review the proposed changes, then decide (approve/reject); "
            "nothing is applied until they are approved"
        )
    elif status in DEAD_JOB_STATUSES:
        details = OUT / "failed_job.json"
        details.write_text(json.dumps(job, indent=2), encoding="utf-8")
        result["details_file"] = str(details)
        notes.append(clear_dead_run("draft", state["job_id"], status, details))
    return result


def clear_dead_run(step: str, job_id: str, status: str, details_file: Path) -> str:
    """Delete the state a dead job left behind and say what that costs.

    Only a status the server itself calls dead gets here: a poll timeout or
    a network error leaves the state alone, because that job may still be
    running and clearing it would make the next draft pay twice.
    """
    STATE_FILE.unlink(missing_ok=True)
    return (
        f"{step} job {job_id} {status} on the server — details in "
        f"{details_file}; run state cleared, the next draft starts fresh "
        f"(and will bill again)"
    )


def decide_core(decisions: list[dict] | None = None, approve_all: bool | None = None) -> dict:
    if not STATE_FILE.exists():
        raise ValueError(
            "no run state found — run a draft first; there is nothing to decide"
        )
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    reviewed = json.loads((OUT / "pending_changes.json").read_text(encoding="utf-8"))
    if not reviewed:
        raise ValueError("no reviewed pending changes — nothing to decide")

    if decisions is None:
        if approve_all is None:
            raise ValueError(
                "pass either approve_all or a per-change decisions list — "
                "a decision must be explicit, never implied"
            )
        decisions = [
            {"change_id": change["change_id"], "approved": approve_all}
            for change in reviewed
        ]

    client = make_client()
    carry_spent(client, state)
    # the same job can be decided in the SuperDocs app, and SuperDocs lets
    # undecided changes expire; either way the job is no longer waiting for
    # us, and sending a decision it cannot take would stop the run short of
    # the export and the verification
    job = client.wait_for_decision_or_end(state["job_id"], MAX_JOB_WAIT_SECONDS)
    if job.get("status") == "awaiting_approval":
        client.decide_changes(state["session_id"], state["job_id"], decisions)
        notes = [f"decided {len(decisions)} reviewed change(s)"]
        job = client.wait_for_decision_or_end(state["job_id"], MAX_JOB_WAIT_SECONDS)
    else:
        notes = [
            f"job {state['job_id']} was already decided outside this run "
            f"(status {job.get('status')}) — in the SuperDocs app, or its "
            f"proposed changes expired unapproved; continuing to export and "
            f"verification{decided_elsewhere_detail(job)}"
        ]
    status = job.get("status")
    note_remaining(client, notes)
    result = {"status": status, "notes": notes, "ops_spent": client.budget.spent}

    if status == "awaiting_approval":
        # the run goes on: the next decide must start from this count
        save_spent(client, state)
        count = dump_pending_changes(job)
        result["pending_changes"] = count
        result["pending_changes_file"] = str(OUT / "pending_changes.md")
        result["next_step"] = (
            "the model proposed NEW change(s); they are unreviewed — review "
            "and decide again"
        )
        return result
    if status in DEAD_JOB_STATUSES:
        details = OUT / "job_final.json"
        details.write_text(json.dumps(job, indent=2), encoding="utf-8")
        result["details_file"] = str(details)
        notes.append(clear_dead_run("decide", state["job_id"], status, details))
        return result

    markdown = client.export_document(state["session_id"], "markdown")
    (OUT / "final-response.md").write_bytes(markdown)
    docx = client.export_document(state["session_id"], "docx")
    (OUT / "final-response.docx").write_bytes(docx)
    notes.append("exported final-response.md and final-response.docx (free)")

    case_dir = Path(state.get("case_dir", ROOT / "data"))
    requests, petition, _, matches, skipped = load_case(case_dir)
    checklist = saved_checklist(state, requests)
    export_text = markdown.decode("utf-8", errors="replace")
    failures = verify_export(export_text, requests, checklist)
    # the skeleton placed every citation from a real excerpt; an edit round
    # can still corrupt, invent, or DELETE one, so the export is checked
    # against the petition itself before anything is called filed-ready.
    # retrieval is deterministic code, so recomputed matches are the same
    # petition sections the skeleton was built from
    cited = cited_sections_from_export(export_text)
    failures += find_citation_failures(cited, petition)
    failures += missing_citation_failures(cited, requests, matches)
    result["exported"] = {
        "markdown": str(OUT / "final-response.md"),
        "docx": str(OUT / "final-response.docx"),
    }
    result["verification_failures"] = failures
    result["filed_ready"] = not failures
    result["skipped_files"] = skipped
    gap_rows = [
        row.request_id for row in checklist if row.coverage != Coverage.ANSWERED
    ]
    result["verification_file"] = str(
        write_verification_record(state, requests, gap_rows, len(cited), failures, skipped)
    )
    notes.append(f"verification written to {result['verification_file']}")
    STATE_FILE.unlink()
    notes.append("run finished and state cleared")
    return result


def write_verification_record(
    state: dict,
    requests: list,
    gap_rows: list[str],
    citations_checked: int,
    failures: list[str],
    skipped: list[str],
) -> Path:
    """Leave the verdict next to the export, so the output folder answers
    'is this filed-ready?' on its own — the terminal line is gone once
    the window closes. The facts here are the ones the checks already
    computed; nothing is re-judged."""
    stamp = time.strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Verification — {stamp}",
        "",
        f"Session `{state['session_id']}` · job `{state['job_id']}`",
        f"Export: `final-response.md`, `final-response.docx` (same document)",
        "",
    ]
    if failures:
        lines.append("**FILED-READY: no — do not file this document.**")
        lines.append("")
        lines.append("Failures:")
        lines.extend(f"- {failure}" for failure in failures)
    else:
        lines.append("**FILED-READY: yes.**")
        lines.append("")
        lines.append("Checks passed:")
        lines.append(f"- every request keeps its response section ({len(requests)}/{len(requests)})")
        lines.append("- no draft placeholder left in the document")
        lines.append("- every officer quote unaltered")
        lines.append(
            "- evidence-gap language present where the checklist records a gap"
            + (f" ({', '.join(gap_rows)})" if gap_rows else " (none recorded)")
        )
        lines.append(
            f"- {citations_checked} petition citation(s) verbatim, from real "
            f"petition files, none removed"
        )
    if skipped:
        lines.append("")
        lines.append(f"Note — {skipped_files_note(skipped)}")
    lines.append("")
    lines.append(
        "Attorney-support draft. Not legal advice. Every section requires "
        "attorney review before filing."
    )
    lines.append("")
    path = OUT / "verification.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def command_check() -> None:
    result = check_core()
    print(f"key valid; sessions on the account: {result['sessions']}")


def print_skipped_files(result: dict) -> None:
    if result["skipped_files"]:
        print(skipped_files_note(result["skipped_files"]))


def command_preview(case_dir: Path) -> None:
    result = preview_core(case_dir)
    print_skipped_files(result)
    print(f"wrote {result['checklist_file']}")
    for row in result["checklist"]:
        print(f"  {row['request_id']}: {row['coverage']}")


def command_judge(case_dir: Path) -> None:
    result = judge_core(case_dir)
    print_skipped_files(result)
    print(f"case: {result['case']} | ops spent: {result['ops_spent']}")
    print(f"{'':4}{'locator':<14}{'judge':<14}reason")
    for row in result["rows"]:
        print(
            f"{row['request_id']:<4}{row['locator']:<14}"
            f"{row['judge']:<14}{row['reason'][:90]}"
        )


def command_draft(case_dir: Path) -> None:
    result = draft_core(case_dir)
    for note in result["notes"]:
        print(note)
    print(f"job status: {result['status']} | ops spent this run: {result['ops_spent']}")
    if result["status"] == "awaiting_approval":
        print(
            f"{result['pending_changes']} proposed change(s) written to "
            f"{result['pending_changes_file']} — review them, then run: "
            f"python rfe.py decide approve"
        )
    elif "details_file" in result:
        print(f"details in {result['details_file']}")


def command_decide(approve: bool) -> None:
    result = decide_core(approve_all=approve)
    for note in result["notes"]:
        print(note)
    print(f"job status: {result['status']}")
    if result["status"] == "awaiting_approval":
        print(
            f"{result['pending_changes']} NEW change(s) pending — "
            f"read {result['pending_changes_file']} and decide again"
        )
    elif result["status"] == "completed":
        if result["verification_failures"]:
            print("VERIFICATION FAILED:")
            for failure in result["verification_failures"]:
                print(f"  - {failure}")
            print("do not treat this export as filed-ready")
        else:
            print(
                "verification passed: all sections drafted, officer quotes "
                "untouched, gap language intact, petition citations verbatim"
            )
        print(f"verification record: {result['verification_file']}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    command, rest = args[0], args[1:]
    default_case = ROOT / "data"
    try:
        if command == "check":
            command_check()
        elif command == "preview":
            command_preview(Path(rest[0]) if rest else default_case)
        elif command == "judge":
            command_judge(Path(rest[0]) if rest else default_case)
        elif command == "draft":
            command_draft(Path(rest[0]) if rest else default_case)
        elif command == "decide":
            if len(rest) != 1 or rest[0] not in ("approve", "reject"):
                raise SystemExit("usage: python rfe.py decide approve|reject")
            command_decide(rest[0] == "approve")
        else:
            raise SystemExit(f"unknown command '{command}'\n\n{__doc__}")
    except (SuperDocsError, ValueError) as e:
        raise SystemExit(str(e)) from e


if __name__ == "__main__":
    main()
