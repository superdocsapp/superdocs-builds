"""
propose_edits.py

For every (change, article) pair that find_affected.py marked as affected,
proposes a single surgical sentence-level edit -- not a rewrite of the
article. Each proposal quotes the exact current sentence, gives a replacement
sentence, and a one-line instruction describing the change.

Pairs that find_affected.py could only mark "could_not_assess" are passed
through to a needs_human_review list instead of being given a fabricated edit.

No external LLM API is called; the edits below were drafted by Claude (Claude
Code) against the actual article text at authoring time.

Usage:
    python propose_edits.py
Reads affected_articles.json (produced by find_affected.py) and articles.json.
Writes proposed_edits.json.
"""
import datetime
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ARTICLES_FILE = BASE_DIR / "articles.json"
AFFECTED_FILE = BASE_DIR / "affected_articles.json"
OUTPUT_FILE = BASE_DIR / "proposed_edits.json"

# (change_id, article_id) -> {current_sentence, suggested_sentence, instruction}
EDITS = {
    ("chg-01", "art-003"): {
        "current_sentence": "Currently, each key can make up to 100 requests per minute across all endpoints.",
        "suggested_sentence": "Currently, each key can make up to 500 requests per minute across all endpoints.",
        "instruction": "Replace '100 requests per minute' with '500 requests per minute'.",
    },
    ("chg-01", "art-004"): {
        "current_sentence": "consider spreading requests across a longer window or batching calls rather than firing them all at once",
        "suggested_sentence": "consider spreading requests across a longer window or batching calls rather than firing them all at once -- though most integrations have plenty of headroom under the current 500-request-per-minute default",
        "instruction": "Append a clause noting the higher default limit so the batching advice doesn't read as overly cautious.",
    },
    ("chg-01", "art-005"): {
        "current_sentence": "if you're checking for updates more than once every second or two, you're a good candidate for webhooks instead of polling",
        "suggested_sentence": "if you're checking for updates more than a few times per second, you're a good candidate for webhooks instead of polling",
        "instruction": "Loosen the polling threshold to reflect the new, higher per-key throughput ceiling.",
    },
    ("chg-02", "art-011"): {
        "current_sentence": "click the 'Export' button in the top toolbar",
        "suggested_sentence": "click the 'Download' button in the top toolbar",
        "instruction": "Replace 'Export' with 'Download' (button label) throughout this article.",
    },
    ("chg-02", "art-012"): {
        "current_sentence": "uses the same generation process as clicking the export icon in the toolbar yourself",
        "suggested_sentence": "uses the same generation process as clicking the Download icon in the toolbar yourself",
        "instruction": "Replace 'export icon' with 'Download icon' to match the renamed toolbar action.",
    },
    ("chg-02", "art-017"): {
        "current_sentence": "click the export icon at the top of the log to save the filtered results as a CSV file",
        "suggested_sentence": "click the Download icon at the top of the log to save the filtered results as a CSV file",
        "instruction": "Replace 'export icon' with 'Download icon' to match the renamed toolbar action.",
    },
    ("chg-03", "art-006"): {
        "current_sentence": "it includes core features, community support, and 5GB of cloud storage per team",
        "suggested_sentence": "it includes core features, community support, and 20GB of cloud storage per team",
        "instruction": "Replace '5GB' with '20GB' in the Starter plan description.",
    },
    ("chg-03", "art-007"): {
        "current_sentence": "dropping down to the smaller allowance on the entry-level plan could put you over the cap, and you'll need to free up space or archive old exports first",
        "suggested_sentence": "the entry-level plan's allowance is now large enough that this is rarely an issue, but it's still worth checking your usage before downgrading",
        "instruction": "Soften the downgrade warning now that the Starter allowance is 20GB instead of 5GB.",
    },
    ("chg-03", "art-013"): {
        "current_sentence": "On the Starter plan, this allowance is 5GB per team",
        "suggested_sentence": "On the Starter plan, this allowance is 20GB per team",
        "instruction": "Replace '5GB' with '20GB'.",
    },
    ("chg-04", "art-009"): {
        "current_sentence": "Both formats are currently supported side by side, so if you set up your integration a while ago, check which delivery format your endpoint is using before assuming your parsing logic matches what we now recommend for new integrations.",
        "suggested_sentence": "v1 has been retired and no longer delivers events -- any integration still receiving XML payloads must migrate to v2 before the cutover date or it will stop receiving webhooks.",
        "instruction": "Replace the 'both formats are currently supported side by side' sentence with a statement that v1 is retired.",
    },
    ("chg-04", "art-010"): {
        "current_sentence": "these older connections continue to function for now, but we recommend checking your integration's documentation to confirm it's using our currently recommended delivery method, since older formats are being phased out over time",
        "suggested_sentence": "these older connections have been retired and no longer deliver events -- confirm your integration has migrated to our current (v2) webhook format",
        "instruction": "Change 'continue to function for now' to state plainly that the legacy format has been retired.",
    },
    ("chg-05", "art-001"): {
        "current_sentence": "the link is single-use and expires 24 hours after it's sent",
        "suggested_sentence": "the link is single-use and expires 1 hour after it's sent",
        "instruction": "Replace '24 hours' with '1 hour'.",
    },
    ("chg-05", "art-002"): {
        "current_sentence": "the reset link sent to your inbox will stay active for a while after it's issued, so there's no need to rush back to your email the moment you request it",
        "suggested_sentence": "the reset link sent to your inbox expires within an hour, so check your email and use it promptly after requesting it",
        "instruction": "Reverse the guidance: state that the reset link expires quickly rather than implying there's no rush.",
    },
    ("chg-06", "art-014"): {
        "current_sentence": "Anyone you invite as an Editor today can create, modify, and delete any content in the workspace -- essentially everything short of billing and member management.",
        "suggested_sentence": "Anyone you invite as an Editor can create, modify, and delete any content in the workspace; if they only need to create and edit without delete or publish rights, invite them as a Contributor instead.",
        "instruction": "Add a mention of the new Contributor role as a lighter-weight alternative to Editor.",
    },
    ("chg-06", "art-015"): {
        "current_sentence": "Cascade currently has four permission levels: Owner, Admin, Editor, and Viewer.",
        "suggested_sentence": "Cascade currently has five permission levels: Owner, Admin, Editor, Contributor, and Viewer.",
        "instruction": "Update the role count and list to include the new Contributor level between Editor and Viewer.",
    },
}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def analyze(articles, affected_result):
    """Pure function: given loaded articles + find_affected's report, return proposed edits."""
    article_lookup = {a["id"]: a for a in articles}

    edits_out = []
    needs_review = []

    for change_block in affected_result["results"]:
        cid = change_block["change_id"]

        for entry in change_block["affected_articles"]:
            aid = entry["article_id"]
            if aid not in article_lookup:
                continue
            edit = EDITS.get((cid, aid))
            if edit is None:
                needs_review.append(
                    {
                        "change_id": cid,
                        "change_title": change_block["change_title"],
                        "article_id": aid,
                        "article_title": article_lookup[aid]["title"],
                        "note": "Marked affected but no drafted edit is on file -- needs a human to write one.",
                    }
                )
                continue
            edits_out.append(
                {
                    "change_id": cid,
                    "change_title": change_block["change_title"],
                    "article_id": aid,
                    "article_title": article_lookup[aid]["title"],
                    "mention_type": entry["mention_type"],
                    "confidence": entry["confidence"],
                    **edit,
                }
            )

        for entry in change_block["could_not_assess"]:
            aid = entry["article_id"]
            if aid not in article_lookup:
                continue
            needs_review.append(
                {
                    "change_id": cid,
                    "change_title": change_block["change_title"],
                    "article_id": aid,
                    "article_title": article_lookup[aid]["title"],
                    "note": "Confidence too low to draft a surgical edit automatically -- " + entry["reason"],
                }
            )

    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "edit_count": len(edits_out),
        "edits": edits_out,
        "needs_human_review": needs_review,
    }


def main():
    articles = load_json(ARTICLES_FILE)
    affected = load_json(AFFECTED_FILE)
    result = analyze(articles, affected)
    save_json(OUTPUT_FILE, result)
    print(
        f"propose_edits: drafted {len(result['edits'])} surgical edits, "
        f"{len(result['needs_human_review'])} flagged for human review. Wrote {OUTPUT_FILE.name}"
    )


if __name__ == "__main__":
    main()
