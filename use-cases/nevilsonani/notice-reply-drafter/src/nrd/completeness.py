"""Completeness verification - counted where we promise complete.

A scrutiny reply that skips a discrepancy is worse than no reply. The
verifier parses the NOTICE for its numbered discrepancies, then checks the
exported reply: every discrepancy answered, notice identifiers quoted
exactly, every promised annexure listed, and no invented-figure placeholder
left unfilled. Any miss fails the run."""
from __future__ import annotations

import re
from pathlib import Path

import yaml


def verify(reply_md: Path, case_dir: Path) -> dict:
    notice = (case_dir / "notice-ASMT10.txt").read_text(encoding="utf-8")
    facts = yaml.safe_load((case_dir / "case_facts.yaml").read_text(encoding="utf-8"))
    reply = reply_md.read_text(encoding="utf-8").replace("\\_", "_")
    reply_flat = re.sub(r"\s+", " ", reply)

    problems: list[str] = []

    notice_discrepancies = sorted(set(
        int(n) for n in re.findall(r"^Discrepancy (\d+):", notice, re.MULTILINE)
    ))
    # substance over format: a discrepancy counts as answered when the reply
    # carries its case-fact position - the annexure label AND at least one of
    # its distinctive figures - regardless of heading or table layout
    facts_by_no = {r["discrepancy"]: r for r in facts.get("replies", [])}
    for n in notice_discrepancies:
        r = facts_by_no.get(n)
        if r is None:
            problems.append(f"discrepancy {n} has no position in case_facts.yaml")
            continue
        figures = [str(v) for v in (r.get("figures") or {}).values()]
        if figures and not any(f in reply_flat for f in figures):
            problems.append(
                f"discrepancy {n}: none of its case-fact figures appear in the reply"
            )

    for ident, label in [
        (facts["notice_ref"], "notice reference"),
        (facts["notice_din"], "DIN"),
        (facts["gstin"], "GSTIN"),
    ]:
        if ident not in reply_flat:
            problems.append(f"{label} '{ident}' not quoted in the reply")

    for r in facts.get("replies", []):
        annex = r.get("annexure", "")
        label = annex.split("-")[0].strip()  # e.g. "Annexure A"
        if label and label not in reply_flat:
            problems.append(f"promised '{label}' is not cited in the reply")

    for placeholder in re.findall(r"\[(?:notice reference|DIN|GSTIN|client name|"
                                  r"period|firm name|date|prayer paragraph)[^\]]*\]",
                                  reply, re.IGNORECASE):
        problems.append(f"template placeholder left unfilled: {placeholder}")

    return {
        "discrepancies_in_notice": len(notice_discrepancies),
        "problems": problems,
        "ok": not problems and len(notice_discrepancies) > 0,
    }


def print_report(result: dict) -> None:
    print(f"completeness check: {result['discrepancies_in_notice']} discrepancies "
          f"in the notice")
    for p in result["problems"]:
        print(f"  MISSING: {p}")
    print("completeness: PASS - every point answered, every identifier quoted"
          if result["ok"] else
          "completeness: FAIL - the reply does not fully answer the notice")
