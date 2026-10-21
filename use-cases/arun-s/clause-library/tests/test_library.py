"""Keyless proof: plain-language search finds the right topic + ladder, and the drift
audit flags aligned / drifted / missing clauses as a reviewable list (not a rewrite)."""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from library import ClauseLibrary

LIB = ClauseLibrary.load(str(ROOT / "sample_library.json"))
CONTRACT = (ROOT / "sample_contract.txt").read_text(encoding="utf-8")


def test_find_matches_topic_from_a_paraphrase():
    # the query wording is not the clause wording — it matches by meaning/terms
    res = LIB.find("how much can we be forced to pay — a cap on liability and damages")
    assert res["topic"] == "limitation_of_liability"
    assert res["ladder"][0]["position"] == "preferred"          # preferred first...
    assert [c["position"] for c in res["ladder"]] == ["preferred", "fallback-1", "fallback-2"]  # ...then the ladder


def test_search_returns_ranked_candidates():
    res = LIB.search("terminate the contract on notice", k=2)
    assert res[0]["topic"] == "termination_for_convenience"


def test_audit_classifies_each_clause():
    a = {r["topic"]: r for r in LIB.audit(CONTRACT)}
    assert a["limitation_of_liability"]["status"] == "aligned"   # copied verbatim from the library
    assert a["termination_for_convenience"]["status"] == "aligned"
    assert a["confidentiality"]["status"] == "drifted"           # reworded "secrecy" clause
    assert a["governing_law"]["status"] == "missing"             # no such clause in the draft


def test_audit_is_a_list_not_a_rewrite():
    a = LIB.audit(CONTRACT)
    # every item is a reviewable record with an excerpt — the doc is never modified
    assert all({"topic", "status", "similarity", "doc_excerpt"} <= set(r) for r in a)
