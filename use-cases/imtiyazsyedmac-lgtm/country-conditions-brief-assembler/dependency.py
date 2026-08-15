"""
Tracks which propositions depend on which source paragraphs, and answers
the question this build is graded on: "if I remove a source, which
propositions lose support, and how much?"

A proposition's dependency list is built in assemble.py from the exact
excerpts it cites. Removing a source here means simulating that source's
paragraphs disappearing from the pool and recomputing, per proposition,
how many of its citations survive.
"""


def remove_source(propositions, source_ids_to_remove):
    """Return a report: for every proposition, how many excerpts it had
    before, how many remain after removing the given source(s), and which
    excerpts were specifically lost. Accepts a single source_id or a list,
    so compound removals (simulating "what if two sources both turn out to
    be unusable") can be checked the same way as a single removal."""
    if isinstance(source_ids_to_remove, str):
        source_ids_to_remove = [source_ids_to_remove]
    removed = set(source_ids_to_remove)

    report = []
    for prop in propositions:
        remaining = [ex for ex in prop["excerpts"] if ex["source_id"] not in removed]
        lost = [ex for ex in prop["excerpts"] if ex["source_id"] in removed]
        report.append({
            "element_id": prop["element_id"],
            "element_label": prop["element_label"],
            "excerpts_before": len(prop["excerpts"]),
            "excerpts_after": len(remaining),
            "lost_excerpts": [ex["citation"] for ex in lost],
            "fully_unsupported": len(prop["excerpts"]) > 0 and len(remaining) == 0,
        })
    return report


def print_removal_report(report, source_id):
    label = source_id if isinstance(source_id, str) else " + ".join(source_id)
    print(f"\n=== Removing {label} ===")
    any_affected = False
    for r in report:
        if r["lost_excerpts"]:
            any_affected = True
            status = "NOW FULLY UNSUPPORTED" if r["fully_unsupported"] else f"{r['excerpts_after']} excerpt(s) remain"
            print(f"  {r['element_label']}: lost {r['lost_excerpts']} — {status}")
    if not any_affected:
        print(f"  No proposition cited {source_id}; nothing changes.")


if __name__ == "__main__":
    from documents import load_all_sources
    from extract import build_extraction_index
    from assemble import select_excerpts, build_propositions

    docs = load_all_sources()
    index = build_extraction_index(docs)
    props = build_propositions(select_excerpts(index))

    for sid in ["SRC-A", "SRC-B", "SRC-C", "SRC-D"]:
        report = remove_source(props, sid)
        print_removal_report(report, sid)

    # Compound removal: strip every source that supports "nexus" except one,
    # to prove fully_unsupported actually fires when it should.
    compound = ["SRC-A", "SRC-B", "SRC-D"]
    report = remove_source(props, compound)
    print_removal_report(report, compound)
