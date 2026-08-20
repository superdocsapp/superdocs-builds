"""Interim analysis printout for the currently available sheets."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.analysis import analyze
from app.judges import load_score_sheets
from app.pipeline import load_cases

human, auto = load_score_sheets("human"), load_score_sheets("auto")
meta = {c["case_id"]: c for c in load_cases()}
a = analyze(human, auto, meta)

print("cases:", a["case_ids"])
print()
o = a["overall"]
print(f"OVERALL: pct exact {o['percent_agreement']:.2f} | kappa {o['kappa']} "
      f"| weighted kappa {o['kappa_linear_weighted']}")
print()
for d, dim in a["dimensions"].items():
    print(f"{d:22s} pct={dim['percent_agreement']:.2f} kappa={dim['kappa']} "
          f"ci={dim['kappa_ci95']} band={dim['kappa_band']:13s} wkappa={dim['kappa_linear_weighted']}")
print()
print("distributions:", a["distributions"])
print()
print("disagreements >=2:", len(a["disagreements"]))
for dis in a["disagreements"]:
    print(f"  {dis['case_id']} {dis['dimension']}: human={dis['human']} "
          f"auto={dis['auto']} ({dis['diff']:+d})")