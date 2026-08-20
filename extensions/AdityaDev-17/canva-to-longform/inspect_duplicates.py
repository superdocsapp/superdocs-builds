"""
inspect_duplicates.py — shows the actual surrounding context of each
duplicate occurrence, so we can tell whether this is a genuine
duplicated section (a real bug) or one heading plus a legitimate
second mention elsewhere (e.g. a summary reference).
"""
from pathlib import Path

html = Path("consistency_test_output.html").read_text(encoding="utf-8")

for phrase in ["Our Sourcing Story", "Sustainability Commitment"]:
    print(f"=== Occurrences of '{phrase}' ===")
    start = 0
    occurrence = 1
    while True:
        idx = html.find(phrase, start)
        if idx == -1:
            break
        context = html[max(0, idx - 100):idx + 150]
        print(f"\n--- Occurrence {occurrence} ---")
        print(context)
        start = idx + 1
        occurrence += 1
    print("\n")