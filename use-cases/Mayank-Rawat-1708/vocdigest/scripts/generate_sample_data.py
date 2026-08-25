"""
@file: scripts/generate_sample_data.py
@description: Generates the synthetic dataset used for demos and manual testing: 200
    Q3 2026 support conversations for a fictional SaaS company ("Orbin"), plus a Q2 2026
    digest to compare against. All content is invented — no real customer data is used
    or derived from.
@flow: build templated conversations per category with varied phrasing, names, and
    dates -> write conversations CSV, JSON and TXT (one of each supported input format)
    -> write the Q2 digest as DOCX if python-docx is available, else Markdown.
@dependencies:
    - python-docx (optional): produces the .docx prior digest
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

# Fixed seed: the sample data is part of the repo's reproducibility story. Regenerating
# it must produce the same file, or a digest diff would show phantom changes.
SEED = 20260808

# Category -> (count, phrasing templates). Counts match the brief.
CATEGORIES: dict[str, tuple[int, list[str]]] = {
    "export": (
        60,
        [
            "The export button does nothing when I click it. No file, no error, nothing happens at all.",
            "Exporting my board to CSV silently fails every single time. I've tried three browsers.",
            "I click Export and the spinner runs forever, then stops without producing a download.",
            "CSV export has been broken for us all week. This blocks the weekly report I send to my director.",
            "Export to Excel produces a zero-byte file. Opening it just gives an error.",
            "Every export attempt fails without telling me why. There is no error message anywhere.",
            "The export feature stopped working after the last update. It worked fine before that.",
            "I cannot export any of my project data. The download never starts.",
            "Export silently does nothing for boards with more than about 200 items.",
            "Trying to export a filtered view gives me an empty file with only headers.",
        ],
    ),
    "dashboard": (
        45,
        [
            "The dashboard takes over thirty seconds to load every morning. It used to be instant.",
            "Dashboard performance has degraded badly. With twenty projects open it is unusable.",
            "Loading the main dashboard is painfully slow and often times out completely.",
            "Our dashboard hangs on load for close to a minute before anything appears.",
            "The overview page is extremely slow since we passed fifty active projects.",
            "Dashboard load times have roughly tripled in the last month for our whole team.",
            "Every morning the dashboard spins for ages before showing any of our data.",
            "Performance on the dashboard is bad enough that people have stopped using it.",
        ],
    ),
    "notifications": (
        35,
        [
            "Notification emails are not arriving. I checked spam and they are not there either.",
            "I stopped receiving email alerts about task assignments roughly two weeks ago.",
            "Our team is not getting any notification emails, so deadlines are being missed.",
            "Email notifications arrive hours late, if they arrive at all.",
            "I have notifications switched on but nothing ever reaches my inbox.",
            "Mention notifications never send. People assume I am ignoring them.",
            "Digest emails simply stopped. Nothing changed in our settings.",
        ],
    ),
    "mobile": (
        30,
        [
            "The iOS app crashes immediately on launch since the latest update.",
            "Orbin crashes on my iPhone whenever I open a project with attachments.",
            "The mobile app closes itself every time I try to add a comment.",
            "App crashes on iOS 18 as soon as I tap into the board view.",
            "Mobile app is unusable. It crashes within seconds of opening, every time.",
            "The iPhone app force-closes when switching between workspaces.",
        ],
    ),
    "billing": (
        20,
        [
            "The billing portal is confusing. I cannot tell which plan we are actually on.",
            "I cannot find where to update our payment card in the billing section.",
            "The invoice page shows a different amount from what we were charged.",
            "Billing settings are impossible to navigate. I gave up and emailed support.",
            "There is no clear way to see our seat count versus what we are paying for.",
        ],
    ),
    "misc": (
        10,
        [
            "Is there a keyboard shortcut for creating a new task? I could not find one documented.",
            "Can we change the default view for new projects at the workspace level?",
            "Just wanted to say the new timeline view is genuinely excellent. Thank you.",
            "How do I archive a project without deleting its history?",
            "Does Orbin support single sign-on with Okta on the team plan?",
        ],
    ),
}

# Names and companies deliberately included so the anonymizer has real work to do.
FIRST_NAMES = ["Sarah", "Marcus", "Priya", "Tom", "Elena", "Raj", "Chloe", "Diego", "Aisha", "Ben"]
LAST_NAMES = ["Chen", "Okafor", "Nakamura", "Silva", "Novak", "Patel", "Dubois", "Hansen"]
COMPANIES = ["Northwind Logistics", "Vertex Media", "Bluepeak Health", "Corvid Analytics"]

PREFIXES = [
    "Hi, I'm {first} {last} from {company}. ",
    "This is {first} at {company}. ",
    "Hello — {first} {last} here. ",
    "",
    "",
    "",
]
SUFFIXES = [
    " You can reach me at {email}.",
    " My account ID is {acct}.",
    " Ticket reference {ticket} if that helps.",
    " Call me on {phone} if easier.",
    "",
    "",
    "",
]


def generate_conversations(rng: random.Random) -> list[dict[str, str]]:
    """Build the full conversation set with dates spread across Q3."""
    q3_start = date(2026, 7, 1)
    rows: list[dict[str, str]] = []

    for category, (count, templates) in CATEGORIES.items():
        for i in range(count):
            body = templates[i % len(templates)]

            prefix = rng.choice(PREFIXES)
            suffix = rng.choice(SUFFIXES)
            first = rng.choice(FIRST_NAMES)
            last = rng.choice(LAST_NAMES)
            company = rng.choice(COMPANIES)
            fields = {
                "first": first,
                "last": last,
                "company": company,
                "email": f"{first.lower()}.{last.lower()}@{company.split()[0].lower()}.com",
                "acct": f"ACCT-{rng.randint(10000, 99999)}",
                "ticket": f"TKT-{rng.randint(100000, 999999)}",
                "phone": f"555-{rng.randint(200, 999)}-{rng.randint(1000, 9999)}",
            }
            text = (prefix + body + suffix).format(**fields)

            rows.append(
                {
                    "id": f"conv-{len(rows) + 1:04d}",
                    "text": text,
                    "date": (q3_start + timedelta(days=rng.randint(0, 91))).isoformat(),
                    "category": category,
                }
            )

    rng.shuffle(rows)
    return rows


def write_conversations(rows: list[dict[str, str]], out_dir: Path) -> None:
    csv_path = out_dir / "q3_2026_conversations.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["id", "text", "date", "category"])
        writer.writeheader()
        writer.writerows(rows)

    json_path = out_dir / "q3_2026_conversations.json"
    json_path.write_text(
        json.dumps([{k: r[k] for k in ("id", "text", "date")} for r in rows], indent=2),
        encoding="utf-8",
    )

    txt_path = out_dir / "q3_2026_conversations.txt"
    txt_path.write_text(
        "\n".join(r["text"].replace("\n", " ") for r in rows), encoding="utf-8"
    )

    print(f"  {csv_path.name}  ({len(rows)} rows)")
    print(f"  {json_path.name} ({len(rows)} rows)")
    print(f"  {txt_path.name}  ({len(rows)} lines)")


# Q2 themes deliberately use DIFFERENT names from what Q3 clustering will produce, so
# the comparison exercises semantic matching rather than string equality. Volumes are
# chosen to give a mix of growth, shrinkage, stability, and disappearance.
Q2_THEMES = [
    ("Data export reliability", 38, "Customers reported failures when exporting board data."),
    ("Application performance", 61, "Slow load times were reported across the product."),
    ("Email delivery problems", 12, "Some customers reported missing email alerts."),
    ("Onboarding confusion", 24, "New users struggled to complete initial setup."),
    ("Integration setup friction", 17, "Connecting third-party tools required support help."),
]


def write_q2_digest(out_dir: Path) -> Path:
    """Write the prior-quarter digest, preferring DOCX."""
    try:
        import docx
        from docx.shared import Pt
    except ImportError:
        path = out_dir / "q2_2026_digest.md"
        lines = [
            "# Q2 2026 Voice-of-Customer Digest",
            "",
            "Generated 2026-07-01 from 152 support conversations",
            "",
            "## Executive Summary",
            "",
            "Support volume in Q2 was dominated by performance complaints and export "
            "reliability. Onboarding confusion remained material.",
            "",
            "## Top Themes This Quarter",
            "",
            "| Theme | Volume |",
            "| --- | --- |",
        ]
        lines += [f"| {n} | {v} |" for n, v, _ in Q2_THEMES]
        lines += ["", "## Theme Deep Dives", ""]
        for name, volume, desc in Q2_THEMES:
            lines += [f"### {name} — {volume} conversations", "", desc, ""]
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  {path.name} (python-docx unavailable, wrote Markdown)")
        return path

    path = out_dir / "q2_2026_digest.docx"
    document = docx.Document()
    document.add_heading("Q2 2026 Voice-of-Customer Digest", level=0)
    document.add_paragraph("Generated 2026-07-01 from 152 support conversations")

    document.add_heading("Executive Summary", level=1)
    document.add_paragraph(
        "Support volume in Q2 was dominated by performance complaints and export "
        "reliability. Onboarding confusion remained material, and a smaller number of "
        "customers reported problems receiving email alerts."
    )

    document.add_heading("Top Themes This Quarter", level=1)
    table = document.add_table(rows=1, cols=2)
    table.style = "Light Grid Accent 1"
    header = table.rows[0].cells
    header[0].text = "Theme"
    header[1].text = "Volume"
    for name, volume, _ in Q2_THEMES:
        cells = table.add_row().cells
        cells[0].text = name
        cells[1].text = str(volume)

    document.add_heading("Theme Deep Dives", level=1)
    for name, volume, desc in Q2_THEMES:
        document.add_heading(f"{name} — {volume} conversations", level=2)
        para = document.add_paragraph(desc)
        para.runs[0].font.size = Pt(11)

    document.add_heading("Methodology", level=1)
    document.add_paragraph(
        "Themes were identified by manual review of support conversations. Volumes are "
        "conversation counts. Quotes were redacted by hand before publication."
    )
    document.save(str(path))
    print(f"  {path.name} ({len(Q2_THEMES)} prior themes)")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate VocDigest sample data")
    parser.add_argument("--out", default="sample_data", help="output directory")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(SEED)
    rows = generate_conversations(rng)

    total = sum(count for count, _ in CATEGORIES.values())
    assert len(rows) == total, f"expected {total} conversations, built {len(rows)}"

    print(f"Generating sample data in {out_dir}/ (seed {SEED})")
    write_conversations(rows, out_dir)
    write_q2_digest(out_dir)

    print("\nCategory breakdown:")
    for category, (count, _) in CATEGORIES.items():
        print(f"  {category:<15} {count:>3}")
    print(f"  {'TOTAL':<15} {total:>3}")
    print(
        "\nAll content is synthetic. No real customer data was used, and any resemblance "
        "to a real company or person is coincidental."
    )


if __name__ == "__main__":
    main()
