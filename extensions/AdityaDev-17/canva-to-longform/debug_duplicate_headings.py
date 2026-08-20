"""
debug_duplicate_headings.py — checks whether the duplicate headings
in the consistency test are a real content issue or just our regex
double-matching the same HTML.
"""
from pathlib import Path

html = Path("consistency_test_output.html").read_text(encoding="utf-8")

count_sourcing = html.count("Our Sourcing Story")
count_sustainability = html.count("Sustainability Commitment")

print(f"'Our Sourcing Story' appears {count_sourcing} time(s) in the raw HTML")
print(f"'Sustainability Commitment' appears {count_sustainability} time(s) in the raw HTML")

print(f"\nTotal document length: {len(html)} characters")
print(f"\nFull document saved at: consistency_test_output.html — open it in a browser to look directly")