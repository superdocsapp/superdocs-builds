"""
score_freshness.py

Rolls find_affected.py's results up into a single portfolio freshness score,
plus a per-article breakdown and a could-not-assess list pulled out for human
review rather than silently folded into the score.

Scoring model
-------------
Each (change, article) affected-pair has a mention_type ("direct" or
"indirect") and a confidence. We weight direct mentions higher than indirect
ones, since a paraphrased/implied mention is real staleness but typically a
softer editorial fix than a stated-wrong number:

    MENTION_WEIGHT = {"direct": 1.0, "indirect": 0.6}
    staleness_impact(article) = max(MENTION_WEIGHT[mention_type] * confidence)
                                 over every change that affects it, else 0

    portfolio_freshness_score = round(100 * (1 - mean(staleness_impact)), 1)

Articles that only appear in could_not_assess (never in affected_articles)
contribute 0 to the score average -- they are treated as "unknown", not
"fresh" -- and are reported separately along with a coverage_pct that shows
what fraction of the (change, article) relationships flagged as plausibly
relevant were confidently resolved either way.

No external LLM API is called.

Usage:
    python score_freshness.py
Reads affected_articles.json and articles.json.
Writes freshness_score.json.
"""
import datetime
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ARTICLES_FILE = BASE_DIR / "articles.json"
AFFECTED_FILE = BASE_DIR / "affected_articles.json"
OUTPUT_FILE = BASE_DIR / "freshness_score.json"

MENTION_WEIGHT = {"direct": 1.0, "indirect": 0.6}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def analyze(articles, affected_result):
    """Pure function: given loaded articles + find_affected's report, return the freshness report."""
    article_lookup = {a["id"]: a for a in articles}
    article_ids = list(article_lookup.keys())

    # article_id -> list of {change_id, mention_type, confidence, impact}
    affecting = {aid: [] for aid in article_ids}
    could_not_assess = []
    affected_pairs = 0
    cna_pairs = 0

    for change_block in affected_result["results"]:
        cid = change_block["change_id"]
        ctitle = change_block["change_title"]

        for entry in change_block["affected_articles"]:
            aid = entry["article_id"]
            if aid not in affecting:
                continue
            impact = MENTION_WEIGHT[entry["mention_type"]] * entry["confidence"]
            affecting[aid].append(
                {
                    "change_id": cid,
                    "change_title": ctitle,
                    "mention_type": entry["mention_type"],
                    "confidence": entry["confidence"],
                    "impact": round(impact, 4),
                }
            )
            affected_pairs += 1

        for entry in change_block["could_not_assess"]:
            aid = entry["article_id"]
            if aid not in article_lookup:
                continue
            could_not_assess.append(
                {
                    "change_id": cid,
                    "change_title": ctitle,
                    "article_id": aid,
                    "article_title": article_lookup[aid]["title"],
                    "confidence": entry["confidence"],
                    "reason": entry["reason"],
                }
            )
            cna_pairs += 1

    cna_article_ids = {e["article_id"] for e in could_not_assess}

    article_reports = []
    impacts = []
    for aid in article_ids:
        changes_hit = affecting[aid]
        max_impact = max((c["impact"] for c in changes_hit), default=0.0)
        impacts.append(max_impact)

        if max_impact == 0.0:
            status = "unknown" if aid in cna_article_ids else "fresh"
        else:
            top = max(changes_hit, key=lambda c: c["impact"])
            status = "stale-direct" if top["mention_type"] == "direct" else "stale-indirect"

        article_reports.append(
            {
                "article_id": aid,
                "title": article_lookup[aid]["title"],
                "status": status,
                "staleness_impact": round(max_impact, 4),
                "affecting_changes": changes_hit,
                "has_unresolved_question": aid in cna_article_ids,
            }
        )

    mean_impact = sum(impacts) / len(impacts) if impacts else 0.0
    portfolio_score = round(100 * (1 - mean_impact), 1)

    total_relevant_pairs = affected_pairs + cna_pairs
    coverage_pct = (
        round(100 * affected_pairs / total_relevant_pairs, 1) if total_relevant_pairs else 100.0
    )

    summary = {
        "fresh": sum(1 for r in article_reports if r["status"] == "fresh"),
        "stale_direct": sum(1 for r in article_reports if r["status"] == "stale-direct"),
        "stale_indirect": sum(1 for r in article_reports if r["status"] == "stale-indirect"),
        "unknown": sum(1 for r in article_reports if r["status"] == "unknown"),
        "unresolved_pairs": cna_pairs,
    }

    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scoring_method": (
            "portfolio_freshness_score = round(100 * (1 - mean(staleness_impact)), 1); "
            "staleness_impact(article) = max(mention_weight * confidence) across affecting changes, "
            "mention_weight = {direct: 1.0, indirect: 0.6}; articles with no affecting change score 0 impact; "
            "could-not-assess pairs are excluded from impact (treated as unknown, not fresh) and reported separately."
        ),
        "article_count": len(article_ids),
        "portfolio_freshness_score": portfolio_score,
        "coverage_pct": coverage_pct,
        "summary": summary,
        "articles": article_reports,
        "could_not_assess": could_not_assess,
    }


def main():
    articles = load_json(ARTICLES_FILE)
    affected = load_json(AFFECTED_FILE)
    result = analyze(articles, affected)
    save_json(OUTPUT_FILE, result)
    print(
        f"score_freshness: portfolio_freshness_score={result['portfolio_freshness_score']} "
        f"(coverage {result['coverage_pct']}%) across {result['article_count']} articles. "
        f"{result['summary']['stale_direct']} stale-direct, {result['summary']['stale_indirect']} stale-indirect, "
        f"{result['summary']['unknown']} unknown, {len(result['could_not_assess'])} could-not-assess. "
        f"Wrote {OUTPUT_FILE.name}"
    )


if __name__ == "__main__":
    main()
