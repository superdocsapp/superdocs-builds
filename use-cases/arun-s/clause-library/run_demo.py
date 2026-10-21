"""Demo — fully offline (no key needed).

  python run_demo.py                         # search + ladder + drift audit on the samples
  python run_demo.py "cap on liability"      # search your own query
"""
import pathlib
import sys

from library import ClauseLibrary

HERE = pathlib.Path(__file__).resolve().parent
LIB = ClauseLibrary.load(str(HERE / "sample_library.json"))


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "a cap on our liability for damages"
    print(f'SEARCH: "{query}"')
    hit = LIB.find(query)
    note = "  (low confidence — a neural embedder resolves pure synonyms; lexical needs shared terms)" if hit["match_score"] < 0.15 else ""
    print(f"  -> topic: {hit['topic']}  (score {hit['match_score']}){note}")
    print("  fallback ladder:")
    for c in hit["ladder"]:
        print(f"    [{c['position']}] {c['text']}")

    print("\nDRIFT AUDIT of sample_contract.txt (a reviewable list, not a rewrite):")
    for r in LIB.audit((HERE / "sample_contract.txt").read_text(encoding="utf-8")):
        mark = {"aligned": "OK ", "drifted": "~~ ", "missing": "XX "}[r["status"]]
        print(f"  {mark} {r['status']:8} {r['topic']:28} sim={r['similarity']}")


if __name__ == "__main__":
    main()
