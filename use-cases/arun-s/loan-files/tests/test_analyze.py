import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analyze import analyze, classify

def _docs():
    return {p.name: p.read_text() for p in (ROOT / "sample_loan").glob("*.txt")}

def test_classify_by_document_type():
    assert classify("sanction_letter.txt") == "sanctioned"
    assert classify("emi_schedule.txt") == "emi"

def test_loan_file_flags_overdisbursal_and_unaffordable_emi():
    r = analyze(_docs())
    assert r["facts"]["sanctioned"] == 500000 and r["facts"]["disbursed"] == 520000
    rules = {f["rule"] for f in r["findings"]}
    assert "disbursed_not_exceed_sanctioned" in rules
    assert "emi_affordability" in rules            # EMI 35000 > 50% of 60000
    assert r["decision"] == "refer"

def test_clean_loan_file_clears():
    clean = {"sanction.txt": "Sanctioned amount: Rs 500,000.",
             "disbursement.txt": "Disbursed amount: Rs 500,000.",
             "salary.txt": "Net monthly income: Rs 90,000.",
             "emi.txt": "Monthly EMI: Rs 20,000."}
    assert analyze(clean)["decision"] == "clear"
