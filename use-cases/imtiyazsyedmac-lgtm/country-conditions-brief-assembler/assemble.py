"""
Assembles the evidence brief: for each claim element, picks the strongest
supporting excerpt per source (verbatim, cited), writes one proposition per
element, and records the dependency of that proposition on the specific
source paragraphs it cites.

This module produces no new facts -- every excerpt it selects is copied
verbatim from a Paragraph object built by documents.py, and every citation
points at an exact (source_id, paragraph_number).
"""
from collections import defaultdict

from claim_elements import ELEMENTS, relevance_score
from extract import build_extraction_index


def select_excerpts(index):
    """For each element, group its matching paragraphs by source and keep
    only the single highest-scoring paragraph per source -- one clean
    excerpt per source per element, not a keyword-match dump."""
    selected = defaultdict(list)
    for el in ELEMENTS:
        eid = el["id"]
        hits = index.get(eid, [])
        best_per_source = {}
        for h in hits:
            sid = h["document"].source_id
            score = relevance_score(h["paragraph"].text, eid)
            if sid not in best_per_source or score > best_per_source[sid]["score"]:
                best_per_source[sid] = {**h, "score": score}
        selected[eid] = sorted(best_per_source.values(), key=lambda h: h["document"].source_id)
    return selected


def build_propositions(selected):
    """One proposition per claim element. A proposition's 'depends_on' list
    is the exact set of (source_id, paragraph_number) citations it rests on
    -- this is what dependency.py walks when a source is removed."""
    propositions = []
    for el in ELEMENTS:
        eid = el["id"]
        excerpts = selected.get(eid, [])
        propositions.append({
            "element_id": eid,
            "element_label": el["label"],
            "excerpts": [
                {
                    "source_id": h["document"].source_id,
                    "citation": h["paragraph"].citation(),
                    "full_citation": h["document"].full_citation(),
                    "quote": h["paragraph"].text,
                    "polarity": h["polarity"],
                }
                for h in excerpts
            ],
            "depends_on": [(h["document"].source_id, h["paragraph"].number) for h in excerpts],
        })
    return propositions


def verify_verbatim(propositions, source_docs):
    """Every quoted excerpt must be an exact match (not a paraphrase) of the
    paragraph text stored in the source document it cites. Returns the list
    of any mismatches found -- should always be empty, but this is a real
    check, not an assumption."""
    by_id = {(d.source_id, p.number): p.text for d in source_docs for p in d.paragraphs}
    mismatches = []
    for prop in propositions:
        for ex in prop["excerpts"]:
            key = (ex["source_id"], int(ex["citation"].split("¶")[1]))
            original = by_id.get(key)
            if original != ex["quote"]:
                mismatches.append((prop["element_id"], ex["citation"]))
    return mismatches


if __name__ == "__main__":
    from documents import load_all_sources

    docs = load_all_sources()
    index = build_extraction_index(docs)
    selected = select_excerpts(index)
    props = build_propositions(selected)
    mismatches = verify_verbatim(props, docs)
    print(f"Verbatim check: {'PASS' if not mismatches else 'FAIL ' + str(mismatches)}")
    for p in props:
        print(f"\n{p['element_label']} ({len(p['excerpts'])} excerpts)")
        for ex in p["excerpts"]:
            print(f"  {ex['citation']}: \"{ex['quote'][:90]}...\"")
