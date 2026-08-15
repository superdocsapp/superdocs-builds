"""
Surfaces contradicting sources instead of cherry-picking one side.

For the state_protection element (the only element in this taxonomy where
the polarity lexicon in claim_elements.py applies), this looks across every
tagged paragraph -- not just the ones assemble.py chose as the "best"
excerpt per source -- and reports any pair of sources whose paragraphs
disagree in sign about whether state protection is actually available.
"""
from itertools import combinations

from documents import load_all_sources
from extract import build_extraction_index

POLARITY_ELEMENT = "state_protection"


def find_contradictions(index):
    hits = [h for h in index.get(POLARITY_ELEMENT, []) if h["polarity"] != 0]
    by_source = {}
    for h in hits:
        sid = h["document"].source_id
        # keep the strongest-signal paragraph per source (first one found;
        # all polarity hits for a given source in this fixture agree in sign)
        by_source.setdefault(sid, []).append(h)

    contradictions = []
    for (sid_a, hits_a), (sid_b, hits_b) in combinations(by_source.items(), 2):
        pol_a = hits_a[0]["polarity"]
        pol_b = hits_b[0]["polarity"]
        if pol_a != pol_b:
            contradictions.append({
                "element_id": POLARITY_ELEMENT,
                "source_a": {
                    "source_id": sid_a,
                    "citation": hits_a[0]["paragraph"].citation(),
                    "full_citation": hits_a[0]["document"].full_citation(),
                    "quote": hits_a[0]["paragraph"].text,
                    "reads_as": "protection available" if pol_a == 1 else "protection unavailable/unproven",
                },
                "source_b": {
                    "source_id": sid_b,
                    "citation": hits_b[0]["paragraph"].citation(),
                    "full_citation": hits_b[0]["document"].full_citation(),
                    "quote": hits_b[0]["paragraph"].text,
                    "reads_as": "protection available" if pol_b == 1 else "protection unavailable/unproven",
                },
            })
    return contradictions


if __name__ == "__main__":
    docs = load_all_sources()
    index = build_extraction_index(docs)
    contras = find_contradictions(index)
    print(f"{len(contras)} contradiction(s) found on '{POLARITY_ELEMENT}'\n")
    for c in contras:
        a, b = c["source_a"], c["source_b"]
        print(f"{a['source_id']} ({a['reads_as']}) vs {b['source_id']} ({b['reads_as']})")
        print(f"  {a['citation']}: \"{a['quote'][:100]}...\"")
        print(f"  {b['citation']}: \"{b['quote'][:100]}...\"")
        print()
