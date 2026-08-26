"""Clause library + fallback ladder + drift audit.

A firm's approved clauses live in a library (data). A drafter searches it in plain
language and gets the preferred clause plus its fallback ladder; a second command audits
a whole document and flags every clause that has drifted from the library. Search is
semantic (embeddings), not keyword; the audit produces a reviewable LIST, never a rewrite.
"""
from __future__ import annotations
import json
import re

from embed import embed, cosine

LADDER_ORDER = {"preferred": 0, "fallback-1": 1, "fallback-2": 2, "fallback-3": 3}


class ClauseLibrary:
    def __init__(self, clauses: list[dict]):
        self.clauses = clauses
        for c in self.clauses:
            c["_vec"] = embed(c["text"] + " " + " ".join(c.get("tags", [])))

    @classmethod
    def load(cls, path: str) -> "ClauseLibrary":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f)["clauses"])

    def _view(self, c: dict, score: float | None = None) -> dict:
        d = {k: c[k] for k in ("id", "topic", "position", "text")}
        if score is not None:
            d["score"] = round(score, 3)
        return d

    def search(self, query: str, k: int = 3) -> list[dict]:
        """Plain-language search — returns the best-matching clauses across topics."""
        q = embed(query)
        ranked = sorted(self.clauses, key=lambda c: cosine(q, c["_vec"]), reverse=True)
        return [self._view(c, cosine(q, c["_vec"])) for c in ranked[:k]]

    def find(self, query: str) -> dict:
        """The drafter's main action: match a plain-language query to a topic and return
        the preferred clause with its fallback ladder beneath it."""
        q = embed(query)
        best: dict[str, float] = {}
        for c in self.clauses:
            s = cosine(q, c["_vec"])
            if s > best.get(c["topic"], -1.0):
                best[c["topic"]] = s
        topic = max(best, key=best.get)
        return {"topic": topic, "match_score": round(best[topic], 3), "ladder": self.ladder(topic)}

    def preferred(self, topic: str) -> dict | None:
        return next((c for c in self.clauses if c["topic"] == topic and c["position"] == "preferred"), None)

    def ladder(self, topic: str) -> list[dict]:
        """The preferred clause + its ordered fallbacks for a topic."""
        cs = [c for c in self.clauses if c["topic"] == topic]
        return [self._view(c) for c in sorted(cs, key=lambda c: LADDER_ORDER.get(c["position"], 9))]

    def topics(self) -> list[str]:
        return sorted({c["topic"] for c in self.clauses})

    def audit(self, document_text: str, aligned_at: float = 0.75, drift_at: float = 0.40) -> list[dict]:
        """For every library topic, find the closest clause in the document and classify it:
        aligned / drifted / missing. A reviewable list, not a rewrite."""
        paras = [p.strip() for p in re.split(r"\n\s*\n", document_text) if p.strip()]
        pvecs = [(p, embed(p)) for p in paras]
        out = []
        for topic in self.topics():
            pref = self.preferred(topic)
            if not pref:
                continue
            best_p, best_s = "", -1.0
            for p, pv in pvecs:
                s = cosine(pref["_vec"], pv)
                if s > best_s:
                    best_s, best_p = s, p
            status = "aligned" if best_s >= aligned_at else ("drifted" if best_s >= drift_at else "missing")
            out.append({"topic": topic, "status": status, "similarity": round(best_s, 3),
                        "preferred_id": pref["id"], "doc_excerpt": best_p[:140]})
        return out
