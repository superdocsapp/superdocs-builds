"""Offline integrity self-check for the study (no API calls, no spend).

Verifies: rubric schema, case definitions, edit artifacts for every case,
both raters' score sheets, statistics correctness on hand-derived examples,
Landis-Koch band edges, report rendering, exported files, ledger sanity,
and that no real API keys are committed anywhere except .env.

Run:  python scripts/selftest.py   (exit 0 = all checks pass)
"""

import json
import re
import sys
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.analysis import band, cohens_kappa, percent_agreement  # noqa: E402
from app.budget import BudgetGuard  # noqa: E402
from app.judges import load_score_sheets  # noqa: E402
from app.pipeline import load_cases  # noqa: E402
from app.report import _md_to_html, build_report  # noqa: E402
from app.rubric import DIMENSION_IDS, load_rubric, valid_score  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {label}" + (f"  ({detail})" if detail else ""))
    if not ok:
        FAILURES.append(label)


def load_env_keys() -> dict:
    env = {}
    path = config.BASE_DIR / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main() -> int:
    print("Edit-Quality Rubric study self-check\n")

    # --- rubric schema -----------------------------------------------------
    rubric = load_rubric()
    dims = rubric["dimensions"]
    check("rubric has exactly 6 dimensions", len(dims) == 6)
    check("rubric dimension ids match DIMENSION_IDS",
          [d["id"] for d in dims] == DIMENSION_IDS)
    for d in dims:
        anchors = d.get("anchors", {})
        check(f"rubric {d['id']} has anchors 1-4",
              all(str(s) in anchors and anchors[str(s)].strip() for s in range(1, 5)))

    # --- cases --------------------------------------------------------------
    cases = load_cases()
    check("11 cases defined", len(cases) == 11, str(len(cases)))
    for c in cases:
        corpus_file = config.CORPUS_DIR / c["doc_file"]
        check(f"case {c['case_id']} corpus file exists", corpus_file.exists(), c["doc_file"])

    # --- edit artifacts ------------------------------------------------------
    for c in cases:
        cid = c["case_id"]
        d = config.EDITS_DIR / cid
        needed = ["before.md", "before.html", "after.md", "after.html", "after.docx",
                  "record.json", "job_final.json", "pending_changes.json", "upload.json"]
        missing = [f for f in needed if not (d / f).exists()]
        check(f"case {cid} has all edit artifacts", not missing, ",".join(missing) or "ok")
        rec_path = d / "record.json"
        if rec_path.exists():
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
            check(f"case {cid} record completed", rec.get("status") == "completed", rec.get("status", "?"))
            noop = ((rec.get("steps") or {}).get("approve") or {}).get("note")
            noop = noop and "no pending changes" in noop
        else:
            noop = False
        before_txt = (d / "before.md").read_text(encoding="utf-8") if (d / "before.md").exists() else None
        after_txt = (d / "after.md").read_text(encoding="utf-8") if (d / "after.md").exists() else None
        if before_txt is None or after_txt is None:
            check(f"case {cid} edited doc differs from source", True, "missing md")
        elif noop:
            check(f"case {cid} is the no-op case (docs identical)", before_txt == after_txt)
        else:
            check(f"case {cid} edited doc differs from source", before_txt != after_txt)

    # --- score sheets ---------------------------------------------------------
    human, auto = load_score_sheets("human"), load_score_sheets("auto")
    check("11 human sheets", len(human) == 11, str(len(human)))
    check("11 auto sheets", len(auto) == 11, str(len(auto)))
    check("human and auto cover the same cases", set(human) == set(auto))
    expected = {c["case_id"] for c in cases}
    check("sheets cover exactly the study cases", set(human) == expected)
    for cid, sheet in human.items():
        bad = [d for d, s in sheet["scores"].items() if not valid_score(s)]
        check(f"human sheet {cid} has valid 1-4 scores for all dims", not bad, ",".join(bad) or "ok")
    for cid, sheet in auto.items():
        bad = [d for d, s in sheet["scores"].items() if not valid_score(s)]
        check(f"auto sheet {cid} has valid 1-4 scores for all dims", not bad, ",".join(bad) or "ok")
        check(f"auto sheet {cid} records provider/model",
              bool(sheet.get("provider")) and bool(sheet.get("model")))

    # --- statistics on hand-derived examples -----------------------------------
    perfect = [(1, 1), (2, 2), (3, 3), (4, 4)]
    check("kappa perfect agreement = 1.0", cohens_kappa(perfect) == 1.0)
    check("kappa random agreement = 0.0", cohens_kappa([(1, 1), (2, 1), (1, 2), (2, 2)]) == 0.0)
    unbalanced = [(1, 1), (1, 1), (1, 2), (2, 1)]
    check("kappa unbalanced ≈ -1/3",
          abs(cohens_kappa(unbalanced) - (-1.0 / 3.0)) < 1e-9,
          str(cohens_kappa(unbalanced)))
    check("kappa single category = 1.0", cohens_kappa([(4, 4), (4, 4)]) == 1.0)
    check("percent agreement = 0.75", percent_agreement([(1, 1), (2, 2), (3, 3), (4, 2)]) == 0.75)
    edge = [
        (0.81, "almost perfect"), (0.61, "substantial"), (0.607, "moderate"),
        (0.41, "moderate"), (0.409, "fair"), (0.21, "fair"), (0.209, "slight"),
        (0.0, "slight"), (-0.01, "poor"),
    ]
    for value, label in edge:
        check(f"band({value}) = {label}", band(value) == label)

    # --- report ----------------------------------------------------------------
    md = build_report()
    for marker in ("## 1.", "## 4. Actual spend", "## 6. Inter-rater agreement",
                   "## 7. Disagreement review", "Cohen's kappa"):
        check(f"report contains '{marker}'", marker in md)
    check("report contains 'Confusion matrices'", "Confusion matrices" in md)
    html_out = _md_to_html(md)
    check("html conversion contains tables", "<table>" in html_out)
    check("html conversion has no stray bold markers", "**" not in html_out)

    # --- exported files ----------------------------------------------------------
    pdf = config.REPORT_DIR / "study_report.pdf"
    docx = config.REPORT_DIR / "study_report.docx"
    check("study_report.pdf exists", pdf.exists())
    check("study_report.docx exists", docx.exists())
    if pdf.exists():
        head = pdf.read_bytes()[:5]
        check("pdf is a real PDF", head == b"%PDF-")
    if docx.exists():
        ok_docx = zipfile.is_zipfile(docx)
        has_doc = False
        if ok_docx:
            with zipfile.ZipFile(docx) as z:
                has_doc = "word/document.xml" in z.namelist()
        check("docx is a real OOXML package with document.xml", ok_docx and has_doc)

    # --- ledger -------------------------------------------------------------------
    guard = BudgetGuard()
    rows = guard.load_ledger()
    spent = sum(int(r.get("ops_charged", 0)) for r in rows)
    check("ledger spend == sum of ops_charged", guard.total_spend() == spent)
    check("no negative ops charged", all(int(r.get("ops_charged", 0)) >= 0 for r in rows))
    check("spend within stated cap", spent <= guard.cap_ops, f"{spent} <= {guard.cap_ops}")
    billable = [r for r in rows if r.get("was_billable")]
    check("every billable call charged >= 1 op",
          all(int(r.get("ops_charged", 0)) >= 1 for r in billable))
    print(f"      ledger: {len(rows)} entries, {len(billable)} billable, {spent} ops spent")

    # --- no committed secrets ---------------------------------------------------------
    env = load_env_keys()
    secrets = {k: v for k, v in env.items() if v and k in
               ("SUPERDOCS_API_KEY", "GEMINI_API_KEY")}
    leaked = []
    for name, value in secrets.items():
        if len(value) < 12:
            continue
        for path in config.BASE_DIR.rglob("*"):
            text_path = str(path).replace("\\", "/")
            if not path.is_file() or path.suffix == ".pyc":
                continue
            if "/.env" in text_path or ".env" in path.name or "__pycache__" in text_path:
                continue
            try:
                if value in path.read_text(encoding="utf-8", errors="ignore"):
                    leaked.append(f"{name} in {path}")
            except OSError:
                continue
    check("no API keys outside .env", not leaked, "; ".join(leaked[:5]))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
