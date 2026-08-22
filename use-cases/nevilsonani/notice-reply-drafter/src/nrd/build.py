"""Orchestration: notice + case facts + firm template -> gated, filing-ready
reply. The one rule: figures come from the case facts or the notice itself;
anything else is 'information awaited from client', never an invention."""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import yaml

from .superdocs import SuperDocs

SKELETON = """<h1>Reply to Notice in FORM GST ASMT-10</h1>
<p>(to be drafted from the firm's standard template)</p>
"""


def _instruction(facts: dict, notice_text: str) -> str:
    facts_block = yaml.safe_dump(facts, sort_keys=False, allow_unicode=True)
    return f"""Draft the complete reply to the GST scrutiny notice below, using the firm's saved template "Reply to GST Scrutiny Notice" (search my templates) as the structure. Replace this document's placeholder entirely, editing IN PLACE - never repeat headings, never append a second document.

ZERO-FABRICATION RULE (most important): every identifier, name, figure and
date must be copied from THE NOTICE or THE CASE FACTS below. Do not invent
ANY reference number, DIN, GSTIN, party name, amount or date. Specifically,
these must appear EXACTLY as written:
- Reference No: {facts['notice_ref']}
- DIN: {facts['notice_din']}
- Client: {facts['client']}, GSTIN {facts['gstin']}
- Tax period: {facts['period']}

THE NOTICE (also attached as notice-ASMT10.txt):
<notice>
{notice_text}
</notice>

CASE FACTS - the only permitted source for explanations and figures:
{facts_block}

HARD RULES:
- Reply to EVERY numbered discrepancy in the notice, in order, under the template's "Reply to Discrepancy N" headings. No discrepancy may be skipped or merged. Each reply must use the position and figures from the case facts for that discrepancy - not generic explanations.
- Fill EVERY bracketed placeholder in the template ([firm name], [date], [Prayer paragraph.], the annexure list, the signatory block, the officer designation from the notice). No square-bracket placeholder may remain in the final document, except the literal phrase "[information awaited from client]" where the case facts are genuinely silent.
- Cite the matching annexure label (Annexure A/B/C) at the end of each reply paragraph.
- Use today's date {time.strftime('%d-%b-%Y')} for the reply date.
- Formal Indian tax-practice register; terse; no marketing language."""


def run_build(case_dir: Path, out_dir: Path, auto_approve: bool = False,
              budget: int | None = None) -> dict:
    case_dir = case_dir.resolve()
    notice_path = case_dir / "notice-ASMT10.txt"
    facts = yaml.safe_load((case_dir / "case_facts.yaml").read_text(encoding="utf-8"))
    sd = SuperDocs(budget=budget)
    session = f"notice-{uuid.uuid4().hex[:10]}"
    report: dict = {"session_id": session, "started": time.time()}

    t = sd.ensure_template(case_dir / "firm_template.md")
    print("firm template:", "already saved" if t["skipped"] else "uploaded (templates surface)")

    up = sd.upload_attachment(session, notice_path)
    job = up.get("job_id")
    if job:
        try:
            sd.wait_job(job, timeout_s=300)
        except Exception:
            time.sleep(15)
    print("notice attached and processed")

    print("drafting reply (review mode) - can take a minute or two")
    job_id = sd.chat_async(
        session,
        _instruction(facts, notice_path.read_text(encoding="utf-8")),
        document_html=SKELETON,
        approval_mode="ask_every_time",
    )
    jobbody = sd.wait_job(job_id)
    pending = (jobbody.get("metadata") or {}).get("pending_changes") or []
    report["job_status"] = jobbody.get("status")

    if jobbody.get("status") == "awaiting_approval" and pending:
        print(f"\n{len(pending)} proposed change(s) await review:")
        decisions = []
        for ch in pending:
            expl = (ch.get("ai_explanation") or "").strip().splitlines()[0][:110]
            print(f"  [{ch.get('operation')}] {ch.get('change_id')}: {expl}")
            if auto_approve:
                decisions.append({"change_id": ch["change_id"], "approved": True})
            else:
                ans = input("    approve? [y/N/feedback] ").strip()
                if ans.lower() == "y":
                    decisions.append({"change_id": ch["change_id"], "approved": True})
                else:
                    decisions.append({"change_id": ch["change_id"], "approved": False,
                                      "feedback": ans if ans and ans.lower() != "n" else "rejected"})
        sd.approve(session, job_id, decisions,
                   default_approved=all(d["approved"] for d in decisions))
        final = sd.wait_job(job_id, timeout_s=600)
        print(f"gate: {sum(d['approved'] for d in decisions)} approved; "
              f"apply -> {final.get('status')}")
    elif jobbody.get("status") == "failed":
        raise SystemExit(f"draft job failed: {str(jobbody)[:300]}")
    else:
        print(f"WARNING: job finished as '{jobbody.get('status')}' with no pending "
              "review - approval_mode was not honored on this path. The export "
              "still goes through the completeness verifier; inspect before filing.")

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"reply-{session[-6:]}"
    for fmt in ("markdown", "docx"):
        data = sd.export(session, fmt)
        ext = "md" if fmt == "markdown" else fmt
        (out_dir / f"{stem}.{ext}").write_bytes(data)
        print(f"exported {out_dir / f'{stem}.{ext}'} ({len(data)} bytes)")
    report["exports"] = [str(out_dir / f"{stem}.md"), str(out_dir / f"{stem}.docx")]
    report["ops_used"] = sd.budget.used
    report["wall_s"] = round(time.time() - report.pop("started"), 1)
    print(f"ops used: {sd.budget.used} (budget {sd.budget.max_ops}); wall {report['wall_s']}s")
    return report
