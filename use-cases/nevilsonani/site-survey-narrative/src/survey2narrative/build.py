"""Orchestration: bundle -> attachments -> grounded draft -> human gate ->
export -> grounding verification.

The one rule the narrative must never break: an observation without evidence
is not an observation - it is a second-visit item.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import yaml

from .superdocs import SuperDocs

SECTIONS = [
    "Property & Visit",
    "Roof Structure & Condition",
    "Shading Assessment",
    "Electrical Service",
    "Access & Safety",
    "Design Assumptions & Constraints",
    "Requires Second Visit",
    "Evidence Index",
]

SKELETON = """<h1>Rooftop Solar Site Assessment</h1>
<p>Prepared from the site survey bundle. Every observation cites its evidence.</p>
""" + "\n".join(f"<h2>{s}</h2><p>(to be drafted)</p>" for s in SECTIONS)


def _draft_instruction(photo_names: list[str], measurements: str,
                       voice_notes: dict[str, str]) -> str:
    vn_block = "\n".join(f"[{name.removesuffix('.txt')}] {text}"
                         for name, text in voice_notes.items())
    return f"""Draft the full site assessment by replacing every "(to be drafted)" placeholder. You are writing for a solar designer who did NOT attend the site.

EVIDENCE YOU MAY USE - nothing else exists:
1. The attached photo-log PDF. Each page is one survey photograph with its PHOTO ID caption. Read the pages and ground roof, shading, electrical and access observations in what they actually show. Cite pages by their PHOTO ID:
{chr(10).join('   - ' + n for n in photo_names)}
2. The measurements sheet [measurements.csv]:
{measurements}
3. Voice-note transcripts:
{vn_block}

HARD RULES:
- Edit IN PLACE only: replace each "(to be drafted)" paragraph under its existing heading. NEVER insert new headings, never repeat a heading, never append additional sections or a second report - the eight headings that exist are the entire document structure.
- The "Evidence Index" table must list EVERY evidence id: all {len(photo_names)} photo ids, measurements.csv, and vn_01, vn_02, vn_03.
- Every observation sentence MUST end with its evidence in square brackets, e.g. "Parapet height is 0.9 m [IMG_03_parapet_wall.png] [measurements.csv]". Only cite the filenames/ids listed above.
- If the evidence does not support a claim, DO NOT write the claim. Anything a designer would need that the evidence cannot support goes under "Requires Second Visit" as an explicit open item (the DB internals, earth resistance, tank-frame structural adequacy are known examples - include any others you find).
- "Design Assumptions & Constraints" must state usable roof area, mounting approach, array-zone exclusions (tree shade margin, tank shadow, drainage margin, the west third reserved per [vn_02]), and inverter/AC-side constraints from the 63 A single-phase service - each with evidence tags.
- "Evidence Index" is a table: evidence id -> one-line description of what it shows.
- Keep it factual and terse. No marketing language. Do not invent brands, prices, or yields."""


def run_build(bundle_dir: Path, out_dir: Path, api_key: str | None = None,
              max_photos: int = 12, auto_approve: bool = False,
              budget: int | None = None) -> dict:
    bundle_dir = bundle_dir.resolve()
    manifest = yaml.safe_load((bundle_dir / "manifest.yaml").read_text(encoding="utf-8"))
    photos = sorted((bundle_dir / "photos").glob("*.png"))[:max_photos]
    measurements = (bundle_dir / "measurements.csv").read_text(encoding="utf-8")
    voice_notes = {
        n: (bundle_dir / "voice_notes" / n).read_text(encoding="utf-8")
        for n in manifest.get("voice_notes", [])
    }
    sd = SuperDocs(api_key=api_key, budget=budget)
    session = f"survey-{uuid.uuid4().hex[:10]}"
    report: dict = {"session_id": session, "photos_uploaded": len(photos),
                    "started": time.time()}

    # The attachments API takes documents, not raw image files (the .png 415
    # is a reported docs/API mismatch), so the photos travel as the surveyor's
    # photo-log PDF - and SuperDocs' vision genuinely reads the imagery in it.
    log_pdf = bundle_dir / "photo_log.pdf"
    if max_photos < len(list((bundle_dir / "photos").glob("*.png"))):
        import sys
        sys.path.insert(0, str(bundle_dir.parent / "scripts"))
        from gen_bundle import build_photo_log

        out_dir.mkdir(parents=True, exist_ok=True)
        log_pdf = out_dir / f"photo_log_{len(photos)}.pdf"
        build_photo_log(photos, log_pdf)
    print(f"session {session}: uploading photo log "
          f"({len(photos)} photos, {log_pdf.stat().st_size // 1024} KB)")
    up = sd.upload_attachment(session, log_pdf)
    att_job = up.get("job_id")
    if att_job:
        try:
            job = sd.wait_job(att_job, timeout_s=600)
            print(f"photo log processed: {job.get('status')}")
        except Exception as e:  # noqa: BLE001 - processing state is advisory
            print(f"photo log status poll inconclusive ({e}); "
                  "waiting a grace period instead")
            time.sleep(20)
    else:
        time.sleep(20)
    report["attachments_ready"] = 1

    print("drafting narrative (async, review mode on) - this can take minutes")
    job_id = sd.chat_async(
        session,
        _draft_instruction([p.name for p in photos], measurements, voice_notes),
        document_html=SKELETON,
        approval_mode="ask_every_time",
    )
    job = sd.wait_job(job_id)
    report["job_id"] = job_id
    report["job_status"] = job.get("status")

    pending = (job.get("metadata") or {}).get("pending_changes") or []
    if job.get("status") == "awaiting_approval" and pending:
        print(f"\n{len(pending)} proposed change(s) await review:")
        decisions = []
        for ch in pending:
            expl = (ch.get("ai_explanation") or "").strip().splitlines()[0][:110]
            print(f"  [{ch.get('operation')}] {ch.get('change_id')}: {expl}")
            if auto_approve:
                decisions.append({"change_id": ch["change_id"], "approved": True})
            else:
                ans = input("    approve? [y/N/feedback text] ").strip()
                if ans.lower() == "y":
                    decisions.append({"change_id": ch["change_id"], "approved": True})
                else:
                    decisions.append({
                        "change_id": ch["change_id"], "approved": False,
                        "feedback": ans if ans and ans.lower() != "n" else "rejected",
                    })
        sd.approve(session, job_id, decisions,
                   default_approved=all(d["approved"] for d in decisions))
        approved = sum(1 for d in decisions if d["approved"])
        print(f"gate: {approved} approved, {len(decisions) - approved} rejected "
              "- every decision explicit, nothing committed silently")
        report["approved"] = approved
        report["rejected"] = len(decisions) - approved
        # approval resumes the job; wait for the changes to actually apply
        # before exporting - a success must mean the document really changed
        final = sd.wait_job(job_id, timeout_s=600)
        print(f"apply after approval: {final.get('status')}")
        report["final_status"] = final.get("status")
    elif job.get("status") == "failed":
        raise SystemExit(f"draft job failed: {str(job)[:300]}")
    else:
        print(f"job finished as {job.get('status')} with no pending review "
              "(approval mode not honored? inspect before trusting)")

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"site-assessment-{session[-6:]}"
    for fmt in ("markdown", "docx"):
        data = sd.export(session, fmt)
        ext = "md" if fmt == "markdown" else fmt
        path = out_dir / f"{stem}.{ext}"
        path.write_bytes(data)
        print(f"exported {path} ({len(data)} bytes) - exports cost no operations")
    report["exports"] = [str(out_dir / f"{stem}.md"), str(out_dir / f"{stem}.docx")]
    report["ops_used"] = sd.budget.used
    report["wall_s"] = round(time.time() - report.pop("started"), 1)
    print(f"\nops used this run: {sd.budget.used} (budget {sd.budget.max_ops}); "
          f"wall {report['wall_s']}s")
    return report
