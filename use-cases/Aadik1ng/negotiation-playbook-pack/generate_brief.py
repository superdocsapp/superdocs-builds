#!/usr/bin/env python3
"""Generate a one-page negotiation brief for an inbound contract, built
entirely on SuperDocs' own document-editing API (upload -> chat -> approve
-> export). The four-call minimum contract from the SuperDocs Round 2 brief.

Usage:
    SUPERDOCS_API_KEY=sk_... python generate_brief.py sample_inbound_contract.md

Requires: httpx, pyyaml  (pip install httpx pyyaml)
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx
import yaml

API_BASE = os.environ.get("SUPERDOCS_API_BASE", "https://api.superdocs.app/v1")
API_KEY = os.environ.get("SUPERDOCS_API_KEY")
HERE = Path(__file__).resolve().parent


def _headers() -> dict:
    if not API_KEY:
        sys.exit("Set SUPERDOCS_API_KEY (see README for the agent-signup flow to get one).")
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def load_playbook() -> list[dict]:
    return yaml.safe_load((HERE / "playbook.yaml").read_text(encoding="utf-8"))


def upload_document(client: httpx.Client, session_id: str, path: Path) -> dict:
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    resp = client.post(
        f"{API_BASE}/documents/upload-base64",
        headers=_headers(),
        json={"document_base64": b64, "filename": path.name, "session_id": session_id, "return_html": False},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def build_brief_instruction(playbook: list[dict]) -> str:
    """One targeted edit instruction, not 15 separate calls -- the brief
    warns to budget operations, and a single well-specified instruction
    lets SuperDocs' own document agent do the comparison, not us re-doing
    its job outside the product."""
    lines = [
        "Append a new section titled 'Negotiation Brief' to the end of this document.",
        "For EACH of the following 15 negotiation points, add one line stating: "
        "the point's topic, then one of exactly three verdicts -- "
        "'Compliant' (the contract meets or beats our opening/concession position), "
        "'Conflicting' (the contract falls short of our worst acceptable position), or "
        "'Silent' (the contract does not address this point at all).",
        "IMPORTANT: a point the contract never mentions must be marked 'Silent', never "
        "'Compliant' -- silence is not agreement.",
        "For any point marked Conflicting or Silent, also name the required approver from "
        "the list below, so escalation routing is visible in the brief.",
        "Quote or closely paraphrase the specific contract clause that drove each verdict "
        "where one exists, so the brief is traceable back to the source text.",
        "",
        "The 15 playbook points (topic | our worst acceptable position | approver if escalated):",
    ]
    for p in playbook:
        floor = p["concession_sequence"][-1] if p.get("concession_sequence") else p["opening_position"]
        lines.append(f"- {p['topic']} | floor: {floor} | approver: {p['approver_role']}")
    return "\n".join(lines)


def chat_async(client: httpx.Client, session_id: str, message: str) -> str:
    resp = client.post(
        f"{API_BASE}/chat/async",
        headers=_headers(),
        json={
            "message": message,
            "session_id": session_id,
            "approval_mode": "ask_every_time",
            "response_mode": "compact",
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["job_id"]


def _pending_changes(job: dict) -> list[dict]:
    """Two places a pending change can show up: metadata.pending_changes
    directly, or -- the documented gotcha -- inside
    metadata.intermediate_responses as a proposed_change_batch event whose
    `content` field is a JSON-encoded STRING needing a second json.loads()."""
    meta = job.get("metadata", {}) or {}
    changes = meta.get("pending_changes") or []
    if changes:
        return changes
    for event in meta.get("intermediate_responses", []) or []:
        if event.get("type") == "proposed_change_batch":
            content = event.get("content")
            if isinstance(content, str):
                content = json.loads(content)  # the documented second-parse gotcha
            changes.extend(content.get("changes", content.get("pending_changes", [])) if isinstance(content, dict) else [])
    return changes


def poll_job(client: httpx.Client, job_id: str, timeout_s: int = 300) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        # compact=false: compact mode has been observed to drop pending_changes
        # even at status=awaiting_approval, contrary to its own documented
        # behavior -- always poll non-compact when we need change_ids.
        resp = client.get(f"{API_BASE}/jobs/{job_id}", headers=_headers(), params={"compact": "false"}, timeout=30)
        resp.raise_for_status()
        job = resp.json()
        status = job.get("status")
        if status in ("awaiting_approval", "completed", "failed", "cancelled"):
            return job
        time.sleep(2)
    sys.exit(f"job {job_id} did not settle within {timeout_s}s")


def approve_all(client: httpx.Client, session_id: str, job_id: str, changes: list[dict]) -> None:
    decisions = [{"change_id": c["change_id"], "approved": True} for c in changes if c.get("change_id")]
    if not decisions:
        return
    resp = client.post(
        f"{API_BASE}/chat/{session_id}/approve",
        headers=_headers(),
        json={"changes": decisions},
        timeout=60,
    )
    resp.raise_for_status()


def export_document(client: httpx.Client, session_id: str, fmt: str) -> str | dict:
    resp = client.post(
        f"{API_BASE}/documents/export",
        headers=_headers(),
        json={"session_id": session_id, "format": fmt, "options": {"filename": "negotiation-brief"}},
        timeout=120,
    )
    resp.raise_for_status()
    if fmt in ("markdown", "txt", "html"):
        return resp.text
    return resp.json()  # binary formats: signed download_url envelope


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: generate_brief.py <inbound_contract_path>")
    contract_path = Path(sys.argv[1])
    if not contract_path.exists():
        sys.exit(f"not found: {contract_path}")

    playbook = load_playbook()
    session_id = f"negbrief-{uuid.uuid4().hex[:8]}"

    with httpx.Client() as client:
        print(f"[1/4] uploading {contract_path.name} into session {session_id} ...")
        upload_document(client, session_id, contract_path)

        print(f"[2/4] sending one targeted edit instruction covering all {len(playbook)} playbook points ...")
        job_id = chat_async(client, session_id, build_brief_instruction(playbook))

        print("      polling for the proposed change ...")
        job = poll_job(client, job_id)
        if job["status"] == "awaiting_approval":
            changes = _pending_changes(job)
            print(f"[3/4] reviewing {len(changes)} proposed change(s), approving ...")
            approve_all(client, session_id, job_id, changes)
            job = poll_job(client, job_id)
        if job["status"] != "completed":
            sys.exit(f"job ended in unexpected state: {job['status']} -- {job}")

        print("[4/4] exporting the final brief ...")
        markdown = export_document(client, session_id, "markdown")
        out_path = contract_path.with_name(contract_path.stem + "_negotiation_brief.md")
        out_path.write_text(markdown, encoding="utf-8")
        print(f"done -- wrote {out_path}")


if __name__ == "__main__":
    main()
