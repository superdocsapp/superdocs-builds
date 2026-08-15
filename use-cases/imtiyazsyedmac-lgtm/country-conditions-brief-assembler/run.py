#!/usr/bin/env python3
"""
Orchestrates one full run: ingest -> tag -> assemble brief -> verify
verbatim -> detect contradictions -> build source packet -> run the
removal test -> write everything to output/.

Usage:
    python3 run.py
"""
from pathlib import Path

from documents import load_all_sources
from claim_elements import ELEMENTS
from extract import build_extraction_index
from assemble import select_excerpts, build_propositions, verify_verbatim
from contradictions import find_contradictions
from dependency import remove_source

OUT_DIR = Path(__file__).parent / "output"


def write_brief(propositions, path):
    lines = ["# Country-Conditions Evidence Brief\n",
             "*Synthetic test case — Republic of Salvarion is fictional; all sources are fabricated test data.*\n"]
    for p in propositions:
        lines.append(f"\n## {p['element_label']}\n")
        if not p["excerpts"]:
            lines.append("_No source in this packet bears on this element. No excerpt is invented to fill the gap._\n")
            continue
        for ex in p["excerpts"]:
            lines.append(f"> \"{ex['quote']}\"\n>\n> — {ex['full_citation']}, {ex['citation']}\n")
    path.write_text("\n".join(lines))


def write_source_packet(source_docs, path):
    lines = ["# Indexed Source Packet\n"]
    for doc in source_docs:
        lines.append(f"\n## {doc.source_id} — {doc.full_citation()}\n")
        for para in doc.paragraphs:
            lines.append(f"**¶{para.number}.** {para.text}\n")
    path.write_text("\n".join(lines))


def write_contradictions(contras, path):
    lines = ["# Contradicting Sources Surfaced\n"]
    if not contras:
        lines.append("None detected.\n")
    for c in contras:
        a, b = c["source_a"], c["source_b"]
        lines.append(f"\n## {c['element_id']}: {a['source_id']} vs {b['source_id']}\n")
        lines.append(f"- **{a['source_id']}** ({a['reads_as']}), {a['citation']}: \"{a['quote']}\"\n")
        lines.append(f"- **{b['source_id']}** ({b['reads_as']}), {b['citation']}: \"{b['quote']}\"\n")
        lines.append("\nBoth are kept in the brief and the source packet. Neither is dropped in favor of the other.\n")
    path.write_text("\n".join(lines))


def write_removal_test(propositions, path):
    lines = ["# Removal Test\n",
             "Demonstrates the requirement: removing a source reports exactly which propositions lose support.\n"]
    for sid in ["SRC-A", "SRC-B", "SRC-C", "SRC-D"]:
        report = remove_source(propositions, sid)
        lines.append(f"\n## Removing {sid}\n")
        affected = [r for r in report if r["lost_excerpts"]]
        if not affected:
            lines.append("No proposition cited this source; nothing changes.\n")
        for r in affected:
            status = "**NOW FULLY UNSUPPORTED**" if r["fully_unsupported"] else f"{r['excerpts_after']} excerpt(s) remain"
            lines.append(f"- {r['element_label']}: lost {r['lost_excerpts']} — {status}\n")

    compound = ["SRC-A", "SRC-B", "SRC-D"]
    report = remove_source(propositions, compound)
    lines.append(f"\n## Compound removal: {' + '.join(compound)} (only SRC-C remains)\n")
    for r in report:
        if r["lost_excerpts"]:
            status = "**NOW FULLY UNSUPPORTED**" if r["fully_unsupported"] else f"{r['excerpts_after']} excerpt(s) remain"
            lines.append(f"- {r['element_label']}: lost {r['lost_excerpts']} — {status}\n")
    path.write_text("\n".join(lines))


def run():
    OUT_DIR.mkdir(exist_ok=True)

    docs = load_all_sources()
    index = build_extraction_index(docs)
    selected = select_excerpts(index)
    propositions = build_propositions(selected)

    mismatches = verify_verbatim(propositions, docs)
    assert not mismatches, f"Verbatim check failed: {mismatches}"

    contras = find_contradictions(index)

    write_brief(propositions, OUT_DIR / "brief.md")
    write_source_packet(docs, OUT_DIR / "source_packet.md")
    write_contradictions(contras, OUT_DIR / "contradictions.md")
    write_removal_test(propositions, OUT_DIR / "removal_test.md")

    total_excerpts = sum(len(p["excerpts"]) for p in propositions)
    elements_with_zero = [p["element_label"] for p in propositions if not p["excerpts"]]

    print(f"Sources ingested: {len(docs)}")
    print(f"Claim elements tracked: {len(ELEMENTS)}")
    print(f"Total excerpts assembled: {total_excerpts}")
    print(f"Elements with no supporting excerpt (honest gap, not invented): {elements_with_zero}")
    print(f"Verbatim check: PASS ({len(mismatches)} mismatches)")
    print(f"Contradictions surfaced: {len(contras)}")
    print(f"Output written to {OUT_DIR}/")


if __name__ == "__main__":
    run()
