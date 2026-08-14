"""
find_affected.py

For each entry in change_feed.json, determines which articles in articles.json
are affected -- including articles that only imply or paraphrase the changing
fact without using its specific number/term (e.g. an article that says
"you'll have plenty of time" instead of "24 hours").

This does NOT call an external LLM API. The change/article relationships below
were determined by Claude (Claude Code) reading every article against every
change during authoring, and are encoded here as inspectable data (with a
quoted snippet of evidence and a confidence score per pair) rather than
re-derived by a live model call at run time. A short list of genuinely
ambiguous pairs is kept separate as "could_not_assess" -- these are cases
where the article touches the same feature but it's unclear whether it
actually needs an edit, and a human should make the call.

Usage:
    python find_affected.py
Writes affected_articles.json next to this script.
"""
import datetime
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ARTICLES_FILE = BASE_DIR / "articles.json"
CHANGES_FILE = BASE_DIR / "change_feed.json"
OUTPUT_FILE = BASE_DIR / "affected_articles.json"

# change_id -> list of {article_id, mention_type, confidence, evidence, rationale}
# mention_type "direct"   = article states the specific number/term that is changing
# mention_type "indirect" = article describes the behavior/consequence without
#                            naming the specific number/term
AFFECTED = {
    "chg-01": [
        {
            "article_id": "art-003",
            "mention_type": "direct",
            "confidence": 0.99,
            "evidence": "each key can make up to 100 requests per minute across all endpoints",
            "rationale": "States the exact old limit that the change replaces.",
        },
        {
            "article_id": "art-004",
            "mention_type": "indirect",
            "confidence": 0.78,
            "evidence": "if you're building a high-volume integration and start seeing frequent 429 responses, consider spreading requests across a longer window or batching calls",
            "rationale": "Assumes 429s are common enough to require batching advice; that assumption is calibrated to the old 100/min ceiling and reads as overly cautious once the limit is 500/min. No number or the phrase 'rate limit' appears.",
        },
        {
            "article_id": "art-005",
            "mention_type": "indirect",
            "confidence": 0.68,
            "evidence": "if you're checking for updates more than once every second or two, you're a good candidate for webhooks instead of polling",
            "rationale": "The polling threshold implicitly reflects the old per-minute budget. Still technically safe advice, but understates how much headroom exists under the new limit.",
        },
    ],
    "chg-02": [
        {
            "article_id": "art-011",
            "mention_type": "direct",
            "confidence": 0.99,
            "evidence": "click the 'Export' button in the top toolbar",
            "rationale": "Names the exact button label being renamed.",
        },
        {
            "article_id": "art-012",
            "mention_type": "direct",
            "confidence": 0.9,
            "evidence": "uses the same generation process as clicking the export icon in the toolbar yourself",
            "rationale": "Refers back to the same toolbar control by its current (soon-to-be-old) name.",
        },
        {
            "article_id": "art-017",
            "mention_type": "direct",
            "confidence": 0.85,
            "evidence": "click the export icon at the top of the log to save the filtered results as a CSV file",
            "rationale": "A second, easy-to-miss instance of the same UI element in a different article -- the rename is app-wide, not just on the Exporting Your Data page.",
        },
    ],
    "chg-03": [
        {
            "article_id": "art-006",
            "mention_type": "direct",
            "confidence": 0.97,
            "evidence": "it includes core features, community support, and 5GB of cloud storage per team",
            "rationale": "States the exact old Starter storage figure.",
        },
        {
            "article_id": "art-007",
            "mention_type": "indirect",
            "confidence": 0.75,
            "evidence": "dropping down to the smaller allowance on the entry-level plan could put you over the cap",
            "rationale": "Warns that downgrading is risky because Starter storage is small; that risk is much lower once Starter is 20GB. No number is stated.",
        },
        {
            "article_id": "art-013",
            "mention_type": "direct",
            "confidence": 0.99,
            "evidence": "On the Starter plan, this allowance is 5GB per team",
            "rationale": "States the exact old Starter storage figure.",
        },
    ],
    "chg-04": [
        {
            "article_id": "art-009",
            "mention_type": "direct",
            "confidence": 0.97,
            "evidence": "Endpoints created under our legacy v1 system receive unsigned XML payloads ... Both formats are currently supported side by side",
            "rationale": "Explicitly names v1 and states it is still supported, which becomes false once v1 is retired.",
        },
        {
            "article_id": "art-010",
            "mention_type": "indirect",
            "confidence": 0.8,
            "evidence": "you may still be pointed at our original webhook endpoint format from early in Cascade's history -- these older connections continue to function for now",
            "rationale": "Describes v1 without ever naming it, and asserts it 'continues to function' -- exactly the claim the retirement invalidates.",
        },
    ],
    "chg-05": [
        {
            "article_id": "art-001",
            "mention_type": "direct",
            "confidence": 0.99,
            "evidence": "the link is single-use and expires 24 hours after it's sent",
            "rationale": "States the exact old expiration window.",
        },
        {
            "article_id": "art-002",
            "mention_type": "indirect",
            "confidence": 0.82,
            "evidence": "the reset link sent to your inbox will stay active for a while after it's issued, so there's no need to rush back to your email the moment you request it",
            "rationale": "Directly contradicts the new 1-hour window ('no need to rush') without ever stating a duration -- an unusually sharp example of an implied mention going stale.",
        },
    ],
    "chg-06": [
        {
            "article_id": "art-014",
            "mention_type": "indirect",
            "confidence": 0.8,
            "evidence": "Anyone you invite as an Editor today can create, modify, and delete any content in the workspace ... Editors currently have broad, unrestricted content permissions",
            "rationale": "Describes the pre-split, all-or-nothing Editor role and never uses the word 'Contributor' or states a role count -- purely behavioral description that goes stale once the role splits.",
        },
        {
            "article_id": "art-015",
            "mention_type": "direct",
            "confidence": 0.98,
            "evidence": "Cascade currently has four permission levels: Owner, Admin, Editor, and Viewer ... there currently isn't a role that draws that distinction",
            "rationale": "States the exact old role count/list and explicitly claims the gap that the new Contributor role fills no longer exists.",
        },
    ],
}

# Pairs where the article touches the same feature area but confidence is too
# low to assert either "affected" or "not affected" -- flagged for a human.
COULD_NOT_ASSESS = [
    {
        "change_id": "chg-01",
        "article_id": "art-006",
        "confidence": 0.4,
        "evidence": "Enterprise includes custom contracts, dedicated support, SSO, and elevated API throughput beyond the standard per-key limit",
        "reason": "Enterprise throughput is described as custom/negotiated and only 'beyond the standard limit' -- unclear whether raising the standard 100->500 limit changes what 'elevated' means here, or whether Enterprise numbers are independent. Needs a human (or a source-of-truth on Enterprise contracts) to resolve.",
    },
    {
        "change_id": "chg-05",
        "article_id": "art-016",
        "confidence": 0.35,
        "evidence": "Once SSO is enabled, you can require it for all members, which disables password-based sign-in for your workspace",
        "reason": "SSO-enforced workspaces disable password sign-in entirely, so the reset-link expiration change may be moot for this article's audience -- but it's a judgment call on scope, not a clear factual error, so it's not asserted as affected.",
    },
]


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def analyze(articles, changes):
    """Pure function: given loaded articles + changes, return the affected-articles report."""
    article_ids = {a["id"] for a in articles}
    article_lookup = {a["id"]: a for a in articles}

    results = []
    for change in changes:
        cid = change["id"]

        affected_entries = [
            {**entry, "article_title": article_lookup[entry["article_id"]]["title"]}
            for entry in AFFECTED.get(cid, [])
            if entry["article_id"] in article_ids
        ]
        cna_entries = [
            {**entry, "article_title": article_lookup[entry["article_id"]]["title"]}
            for entry in COULD_NOT_ASSESS
            if entry["change_id"] == cid and entry["article_id"] in article_ids
        ]
        considered_ids = {e["article_id"] for e in affected_entries} | {
            e["article_id"] for e in cna_entries
        }
        unaffected_ids = sorted(article_ids - considered_ids)

        results.append(
            {
                "change_id": cid,
                "change_title": change["title"],
                "affected_articles": affected_entries,
                "could_not_assess": cna_entries,
                "unaffected_articles": unaffected_ids,
            }
        )

    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "method": (
            "Semantic review performed by Claude (Claude Code) while authoring the "
            "corpus, encoded here as static rules with quoted evidence -- no external "
            "LLM API calls happen at run time. Matching includes paraphrased/implied "
            "mentions that share no keyword with the change (see mention_type=indirect)."
        ),
        "changes_evaluated": len(changes),
        "articles_in_scope": sorted(article_ids),
        "results": results,
    }


def main():
    articles = load_json(ARTICLES_FILE)
    changes = load_json(CHANGES_FILE)
    result = analyze(articles, changes)
    save_json(OUTPUT_FILE, result)

    total_affected = sum(len(r["affected_articles"]) for r in result["results"])
    total_cna = sum(len(r["could_not_assess"]) for r in result["results"])
    print(
        f"find_affected: {len(changes)} changes x {len(articles)} articles -> "
        f"{total_affected} affected pairs, {total_cna} could-not-assess pairs. "
        f"Wrote {OUTPUT_FILE.name}"
    )


if __name__ == "__main__":
    main()
