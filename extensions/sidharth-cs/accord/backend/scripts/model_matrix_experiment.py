"""M1-M6 model matrix experiment — measures whether model_tier +
thinking_depth materially changes SuperDocs edit quality.

Reuses the production code path exactly: render_template for the starter,
SuperDocsClient.upload_base64 for init, build_section_instructions for the
instruction text. The ONLY variable between runs is model_tier /
thinking_depth.

Usage:
  cd zoom-app/backend && PYTHONPATH=. python scripts/model_matrix_experiment.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.drafting.classifier import build_section_instructions
from app.drafting.templates import render_template, SOW
from app.superdocs.client import SuperDocsClient

CONFIGS = [
    ("M1", "core", "balanced"),
    ("M2", "core", "deep"),
    ("M3", "pro", "balanced"),
    ("M4", "pro", "deep"),
    ("M5", "max", "balanced"),
    ("M6", "max", "deep"),
]

TESTS = [
    (
        "T1-timeline",
        "The project starts September 15th and the final website should be delivered by October 30th.",
        [("September 15th", "Timeline"), ("October 30th", "Timeline")],
    ),
    (
        "T2-oos",
        "Payment integration is not part of the scope.",
        [("payment integration", "Out of Scope")],
    ),
    (
        "T3-multi",
        "The project starts September 15th. The final website should be delivered by October 30th. "
        "Our total budget is forty-five thousand dollars. Payment integration is not part of the scope.",
        [
            ("September 15th", "Timeline"),
            ("October 30th", "Timeline"),
            ("45,000", "Budget"),
            ("payment integration", "Out of Scope"),
        ],
    ),
]

T3_REPEATS = 3  # nondeterminism check per config
POLL_INTERVAL = 2.0
POLL_DEADLINE = 300.0


def strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def headings(html: str) -> list[str]:
    return re.findall(r"<h[12][^>]*>(.*?)</h[12]>", html or "", re.IGNORECASE | re.DOTALL)


def section_body(html: str, section_name: str) -> str:
    """Extract the body between a named <h2> and the next heading."""
    m = re.search(
        rf"<h2[^>]*>[^<]*{re.escape(section_name)}[^<]*</h2>(.*?)(?=<h[12][^>]*>|$)",
        html or "", re.IGNORECASE | re.DOTALL,
    )
    return m.group(1) if m else ""


def metrics(html: str, template_html: str, expected_sections: list[tuple[str, str]]) -> dict:
    """Score one result document against the acceptance criteria."""
    text = strip_html(html).lower()
    h = [re.sub(r"<[^>]+>", "", x).strip() for x in headings(html)]
    tpl_h = [re.sub(r"<[^>]+>", "", x).strip() for x in headings(template_html)]

    placed = {}
    for fact, section in expected_sections:
        placed[fact] = fact.lower() in strip_html(section_body(html, section)).lower()

    return {
        "heading_count_before": len(tpl_h),
        "heading_count_after": len(h),
        "headings_intact": h == tpl_h,
        "placeholder_invented": "please fill" in text,
        "table_count": html.count("<table"),
        "duplicate_dates": len(re.findall(r"september 1?5", text)),
        "duplicate_budget": len(re.findall(r"45,?000", text)),
        "placed": placed,
        "negation_in_scope": "not part of the scope" in text,
        "excluded_in_oos": "payment integration" in text,
    }


async def run_test(client, session_id: str, instruction: str, model_tier: str, thinking_depth: str) -> dict:
    start = time.monotonic()
    job = await client.chat_async(
        message=instruction,
        session_id=session_id,
        approval_mode="auto",
        model_tier=model_tier,
        thinking_depth=thinking_depth,
    )
    deadline = time.monotonic() + POLL_DEADLINE
    while time.monotonic() < deadline:
        status = await client.get_job(job.job_id)
        if status.status in ("completed", "failed", "cancelled"):
            latency = time.monotonic() - start
            html = status.document_changes.updated_html if status.document_changes else ""
            return {
                "status": status.status,
                "latency": round(latency, 1),
                "html": html,
                "changes": [
                    {"operation": c.operation, "chunk_id": c.chunk_id}
                    for c in (status.document_changes.changes if status.document_changes else [])
                ],
            }
        await asyncio.sleep(POLL_INTERVAL)
    return {"status": "timeout", "latency": POLL_DEADLINE, "html": "", "changes": []}


async def main() -> None:
    settings = get_settings()
    if not settings.superdocs_api_key:
        print("ERROR: SUPERDOCS_API_KEY not set")
        return
    client = SuperDocsClient(api_key=settings.superdocs_api_key)
    template_html = render_template(SOW, date="August 11, 2026")

    results = {}
    html_dir = Path("/tmp/model_matrix_html")
    html_dir.mkdir(exist_ok=True)
    try:
        for label, tier, depth in CONFIGS:
            for test_name, text, expected in TESTS:
                repeats = T3_REPEATS if test_name == "T3-multi" else 1
                for r in range(repeats):
                    run_key = f"{label}-{test_name}" if repeats == 1 else f"{label}-{test_name}-r{r+1}"
                    # Fresh session per run — same init path as production.
                    upload = await client.upload_base64(
                        file_base64=__import__("base64").b64encode(template_html.encode()).decode(),
                        filename="draft.html",
                        session_id=f"mexp-{label}-{test_name}-{r}-{int(time.time())}",
                        return_html=True,
                    )
                    session_id = upload.session_id
                    # Same instruction-building path as session.py.
                    instructions = build_section_instructions("addition", text, upload.html or "", SOW)
                    outcomes = []
                    for instr in instructions:
                        outcomes.append(await run_test(client, session_id, instr, tier, depth))
                    ok = all(o["status"] == "completed" for o in outcomes)
                    final_html = outcomes[-1]["html"] if outcomes else ""
                    latency = sum(o["latency"] for o in outcomes)
                    ops = len(instructions)
                    m = metrics(final_html, template_html, expected)
                    results[run_key] = {
                        "config": f"{tier}+{depth}",
                        "test": test_name,
                        "ok": ok,
                        "latency": round(latency, 1),
                        "ops": ops,
                        "metrics": m,
                        "statuses": [o["status"] for o in outcomes],
                    }
                    (html_dir / f"{run_key}.html").write_text(final_html)
                    print(json.dumps({k: v for k, v in results[run_key].items() if k != "metrics"}, default=str))
    finally:
        await client.aclose()

    out = Path("/tmp/model_matrix_results.json")
    out.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
