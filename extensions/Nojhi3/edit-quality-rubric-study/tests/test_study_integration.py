"""Integration test on the REAL study data (offline, no API calls): pins the
headline numbers of the completed study so any regression in rubric, scores,
or statistics is caught. If these numbers ever change, the change must be a
deliberate re-run of the study — not a code accident."""

import json
import zipfile

import pytest

from app.analysis import analyze
from app.budget import BudgetGuard
from app.judges import load_score_sheets
from app.pipeline import load_cases
from app.report import build_report


def _case_meta():
    return {c["case_id"]: c for c in load_cases()}


@pytest.fixture(scope="module")
def real_analysis():
    human, auto = load_score_sheets("human"), load_score_sheets("auto")
    assert human and auto, "real score sheets missing"
    return analyze(human, auto, _case_meta())


class TestStudyIntegrity:
    def test_all_cases_scored_by_both_raters(self, real_analysis):
        assert real_analysis["overall"]["n_cases"] == 11
        assert real_analysis["overall"]["n_judgments"] == 66
        assert set(real_analysis["case_ids"]) == {c["case_id"] for c in load_cases()}

    def test_headline_numbers(self, real_analysis):
        o = real_analysis["overall"]
        assert o["percent_agreement"] == 0.758
        assert o["kappa"] == 0.339
        assert o["kappa_linear_weighted"] == 0.405
        assert o["kappa_ci95"][0] < o["kappa_ci95"][1]
        assert -1.0 <= o["kappa_ci95"][0] <= o["kappa_ci95"][1] <= 1.0

    def test_per_dimension_numbers(self, real_analysis):
        expected = {
            "faithfulness": (0.727, 0.56, "moderate", 0.645),
            "fact_accuracy": (0.636, -0.1, "poor", -0.158),
            "content_preservation": (0.909, 0.476, "moderate", 0.476),
            "structural_integrity": (0.545, 0.127, "slight", 0.279),
            "formatting_fidelity": (0.727, 0.0, "slight", 0.0),
            "language_quality": (1.0, 1.0, "almost perfect", 1.0),
        }
        for did, (pct, kappa, band_label, wkappa) in expected.items():
            d = real_analysis["dimensions"][did]
            assert d["n"] == 11
            assert d["percent_agreement"] == pytest.approx(pct, abs=0.001)
            assert d["kappa"] == pytest.approx(kappa, abs=0.001)
            assert d["kappa_band"] == band_label
            assert d["kappa_linear_weighted"] == pytest.approx(wkappa, abs=0.001)

    def test_distributions(self, real_analysis):
        assert real_analysis["distributions"] == {
            "human": {"1": 7, "2": 4, "3": 5, "4": 50},
            "auto": {"1": 2, "2": 6, "3": 4, "4": 54},
        }

    def test_disagreement_review(self, real_analysis):
        dis = real_analysis["disagreements"]
        assert len(dis) == 8
        assert [(d["case_id"], d["dimension"], d["diff"]) for d in dis] == [
            ("contract-01", "faithfulness", 3),
            ("plan-02", "fact_accuracy", -3),
            ("plan-04", "structural_integrity", -3),
            ("plan-04", "formatting_fidelity", -3),
            ("contract-04", "fact_accuracy", 2),
            ("contract-04", "content_preservation", -2),
            ("meeting-03", "structural_integrity", -2),
            ("plan-03", "fact_accuracy", 2),
        ]
        for d in dis:
            assert d["human_evidence"] or d["auto_evidence"], \
                f"disagreement {d['case_id']}/{d['dimension']} has no evidence"

    def test_noop_case_is_identical(self):
        from app import config
        before = (config.EDITS_DIR / "plan-02" / "before.md").read_text(encoding="utf-8")
        after = (config.EDITS_DIR / "plan-02" / "after.md").read_text(encoding="utf-8")
        assert before == after

    def test_every_edited_doc_differs_from_source(self):
        from app import config
        for case in load_cases():
            before = (config.EDITS_DIR / case["case_id"] / "before.md").read_text(encoding="utf-8")
            after = (config.EDITS_DIR / case["case_id"] / "after.md").read_text(encoding="utf-8")
            if case["case_id"] == "plan-02":
                continue  # the no-op case
            assert before != after, f"{case['case_id']} was not actually edited"


class TestLedgerIntegrity:
    def test_actual_spend_within_stated_cap(self):
        guard = BudgetGuard()
        report = guard.report()
        assert report["spent_ops"] <= report["cap_ops"]
        assert report["cap_ops"] == 60

    def test_spend_matches_ledger(self):
        guard = BudgetGuard()
        assert guard.total_spend() == guard.report()["spent_ops"]
        assert guard.report()["spent_ops"] == 12
        assert guard.report()["billable_calls"] == 12

    def test_billable_calls_all_charged(self):
        for e in BudgetGuard().load_ledger():
            if e["was_billable"]:
                assert int(e["ops_charged"]) >= 1


class TestReportArtifacts:
    def test_report_mentions_headline_kappa(self):
        md = build_report()
        assert "0.339" in md
        assert "0.405" in md

    def test_report_has_confusion_matrices(self):
        assert "Confusion matrices" in build_report()

    def test_exported_docx_is_valid(self):
        from app import config
        path = config.REPORT_DIR / "study_report.docx"
        assert path.exists()
        assert zipfile.is_zipfile(path)
        with zipfile.ZipFile(path) as z:
            assert "word/document.xml" in z.namelist()

    def test_exported_pdf_is_valid(self):
        from app import config
        path = config.REPORT_DIR / "study_report.pdf"
        assert path.exists()
        assert path.read_bytes()[:5] == b"%PDF-"

    def test_report_tracks_human_evidence_sparsity(self):
        md = build_report()
        assert "Sparse human evidence" in md


class TestNoSecrets:
    def test_api_keys_not_committed_outside_env(self):
        from app import config
        env_path = config.BASE_DIR / ".env"
        env_text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
        secrets = {}
        for line in env_text.splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                if k.strip() in ("SUPERDOCS_API_KEY", "GEMINI_API_KEY") and v.strip():
                    secrets[k.strip()] = v.strip()
        assert secrets, "no keys found in .env — check fixture assumption"
        for name, value in secrets.items():
            if len(value) < 12:
                continue
            for path in config.BASE_DIR.rglob("*"):
                sp = str(path).replace("\\", "/")
                if not path.is_file() or ".env" in path.name or "__pycache__" in sp or ".git" in sp:
                    continue
                content = path.read_text(encoding="utf-8", errors="ignore")
                assert value not in content, f"{name} leaked into {path}"