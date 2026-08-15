"""
Runs the tagger across every paragraph of every ingested source, producing
an index: element_id -> [ (Paragraph, SourceDocument, polarity) ].

This is the "extraction" stage: it decides which passages bear on which
claim elements. It does not write any new text -- every result here is a
pointer back to an exact (source_id, paragraph_number, verbatim text)
triple, so nothing downstream can drift from what the source actually says.
"""
from collections import defaultdict

from documents import load_all_sources
from claim_elements import ELEMENTS, tag_paragraph, protection_polarity


def build_extraction_index(source_docs):
    index = defaultdict(list)
    for doc in source_docs:
        for para in doc.paragraphs:
            element_ids = tag_paragraph(para.text)
            for eid in element_ids:
                polarity = protection_polarity(para.text) if eid == "state_protection" else 0
                index[eid].append({
                    "paragraph": para,
                    "document": doc,
                    "polarity": polarity,
                })
    return index


if __name__ == "__main__":
    docs = load_all_sources()
    index = build_extraction_index(docs)
    for el in ELEMENTS:
        hits = index.get(el["id"], [])
        print(f"\n{el['id']} ({len(hits)} matching paragraphs):")
        for h in hits:
            pol = {1: "+", -1: "-", 0: " "}[h["polarity"]]
            print(f"  [{pol}] {h['paragraph'].citation()}: {h['paragraph'].text[:80]}...")
