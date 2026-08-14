"""
flag_screenshots.py

For every (change, article) pair that find_affected.py marked as affected,
judges whether the article's screenshot plausibly depicts the specific UI
element that changed (a number, a label, a diagram) -- as opposed to showing
something unrelated (a QR code, a generic marketplace grid, a JSON example
that stays accurate) that just happens to sit on the same page.

This matters because not every affected article's screenshot is stale: e.g.
art-009's screenshot is captioned as the v2 JSON example, which remains
correct after webhook v1 is retired, even though the article's *text* needs
an edit.

No external LLM API is called; these are judgment calls made by Claude
(Claude Code) from the screenshot filename + the article's description of
what the screenshot shows, encoded as data with a confidence score.

Usage:
    python flag_screenshots.py
Reads affected_articles.json and articles.json.
Writes flagged_screenshots.json.
"""
import datetime
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ARTICLES_FILE = BASE_DIR / "articles.json"
AFFECTED_FILE = BASE_DIR / "affected_articles.json"
OUTPUT_FILE = BASE_DIR / "flagged_screenshots.json"

FLAG_THRESHOLD = 0.55

# (change_id, article_id) -> {flagged, confidence, rationale}
SCREENSHOT_FLAGS = {
    ("chg-01", "art-003"): {
        "flagged": True,
        "confidence": 0.9,
        "rationale": "Dashboard screenshot almost certainly renders the numeric per-key rate limit somewhere in the UI.",
    },
    ("chg-01", "art-004"): {
        "flagged": True,
        "confidence": 0.55,
        "rationale": "Key management page may show a per-key quota figure next to each key; moderate confidence only, no explicit description of the number being visible.",
    },
    ("chg-01", "art-005"): {
        "flagged": False,
        "confidence": 0.2,
        "rationale": "Console/error screenshot shows a 429 response, not the numeric rate limit itself.",
    },
    ("chg-02", "art-011"): {
        "flagged": True,
        "confidence": 0.97,
        "rationale": "Screenshot filename and caption are literally of the toolbar button being relabeled.",
    },
    ("chg-02", "art-012"): {
        "flagged": True,
        "confidence": 0.6,
        "rationale": "List view of scheduled exports likely shows the export/download icon in a column or row action menu.",
    },
    ("chg-02", "art-017"): {
        "flagged": True,
        "confidence": 0.55,
        "rationale": "Audit log table view may include the export/download icon in its header toolbar.",
    },
    ("chg-03", "art-006"): {
        "flagged": True,
        "confidence": 0.85,
        "rationale": "Plan comparison table almost certainly renders the storage figure as a table cell.",
    },
    ("chg-03", "art-007"): {
        "flagged": False,
        "confidence": 0.25,
        "rationale": "Confirmation modal most likely just names the plan being switched to, not its storage allowance.",
    },
    ("chg-03", "art-013"): {
        "flagged": True,
        "confidence": 0.9,
        "rationale": "Usage meter screenshots typically render the cap value in the label or tooltip (e.g. 'X of 5GB used').",
    },
    ("chg-04", "art-009"): {
        "flagged": False,
        "confidence": 0.15,
        "rationale": "The example shown is the v2 JSON payload, which stays accurate after v1 is retired -- the stale claim is in the surrounding text, not the image.",
    },
    ("chg-04", "art-010"): {
        "flagged": False,
        "confidence": 0.1,
        "rationale": "Marketplace grid of integration logos is not tied to any specific webhook payload format.",
    },
    ("chg-05", "art-001"): {
        "flagged": True,
        "confidence": 0.75,
        "rationale": "Email screenshot plausibly shows the stated validity window ('this link expires in...') in the email body.",
    },
    ("chg-05", "art-002"): {
        "flagged": False,
        "confidence": 0.1,
        "rationale": "QR code screenshot for 2FA setup is unrelated to password reset link timing.",
    },
    ("chg-06", "art-014"): {
        "flagged": True,
        "confidence": 0.65,
        "rationale": "Role list/dropdown screenshot likely enumerates role names, which gains a new 'Contributor' entry.",
    },
    ("chg-06", "art-015"): {
        "flagged": True,
        "confidence": 0.9,
        "rationale": "The screenshot is a diagram of the permission hierarchy itself, so it directly depicts the role being added.",
    },
}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def analyze(articles, affected_result):
    """Pure function: given loaded articles + find_affected's report, return screenshot flags."""
    article_lookup = {a["id"]: a for a in articles}

    assessments = []
    for change_block in affected_result["results"]:
        cid = change_block["change_id"]
        for entry in change_block["affected_articles"]:
            aid = entry["article_id"]
            if aid not in article_lookup:
                continue
            flag = SCREENSHOT_FLAGS.get((cid, aid))
            if flag is None:
                continue
            assessments.append(
                {
                    "change_id": cid,
                    "change_title": change_block["change_title"],
                    "article_id": aid,
                    "article_title": article_lookup[aid]["title"],
                    "screenshot_filename": article_lookup[aid]["screenshot_filename"],
                    "mention_type": entry["mention_type"],
                    **flag,
                }
            )

    flagged_only = [a for a in assessments if a["flagged"] and a["confidence"] >= FLAG_THRESHOLD]

    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "flag_threshold": FLAG_THRESHOLD,
        "screenshot_assessments": assessments,
        "flagged_for_update": flagged_only,
    }


def main():
    articles = load_json(ARTICLES_FILE)
    affected = load_json(AFFECTED_FILE)
    result = analyze(articles, affected)
    save_json(OUTPUT_FILE, result)
    print(
        f"flag_screenshots: assessed {len(result['screenshot_assessments'])} screenshots, "
        f"{len(result['flagged_for_update'])} flagged for update. Wrote {OUTPUT_FILE.name}"
    )


if __name__ == "__main__":
    main()
