import pathlib
from analyze import analyze
HERE = pathlib.Path(__file__).resolve().parent
docs = {p.name: p.read_text() for p in (HERE / "sample_loan").glob("*.txt")}
r = analyze(docs)
print("facts   :", r["facts"])
print("decision:", r["decision"].upper())
for f in r["findings"]:
    print("  finding:", f["message"])
