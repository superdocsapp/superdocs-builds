"""FastAPI endpoint tests via TestClient against the isolated fixture tree.

The app reads config paths at call time, so monkeypatching config (done by the
`tree` fixture) redirects everything to temp dirs — no real API, no real files."""

import json

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.superdocs_client import SuperDocsClient

client = TestClient(app)


class TestReadEndpoints:
    def test_index(self, tree):
        r = client.get("/")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "Edit-Quality Rubric Study"
        assert "/judge" in body["endpoints"].values()

    def test_rubric(self, tree):
        r = client.get("/rubric")
        assert r.status_code == 200
        dims = r.json()["dimensions"]
        assert len(dims) == 6
        assert {d["id"] for d in dims} == {
            "faithfulness", "fact_accuracy", "content_preservation",
            "structural_integrity", "formatting_fidelity", "language_quality"}

    def test_cases(self, tree):
        r = client.get("/cases")
        assert r.status_code == 200
        assert {c["case_id"] for c in r.json()} == {"plan-01", "meeting-01"}

    def test_budget(self, tree):
        r = client.get("/study/budget")
        assert r.status_code == 200
        body = r.json()
        assert body["cap_ops"] == 60
        assert body["spent_ops"] == 1
        assert body["total_calls_recorded"] == 1


class TestJudgeUI:
    def test_page_lists_scored_and_unedited_cases(self, tree):
        r = client.get("/judge")
        assert r.status_code == 200
        html = r.text
        assert "plan-01" in html
        assert "Add a missing owner to the plan." in html
        assert "edit not run yet" in html  # meeting-01 has no artifacts

    def test_prefills_saved_scores_and_evidence(self, tree):
        html = client.get("/judge").text
        card = html.split("id='plan-01'")[1].split("</form>")[0]
        assert "checked" in card
        assert "owner added" in card  # saved evidence prefilled

    def test_shows_saved_badge_and_progress(self, tree):
        html = client.get("/judge").text
        assert "badge saved" in html
        assert "Saved sheets: human <b>1/2</b>" in html
        assert "automated <b>1/2</b>" in html


class TestSubmitScores:
    def _valid_payload(self):
        return {"case_id": "meeting-01",
                "scores": {d: 4 for d in (
                    "faithfulness", "fact_accuracy", "content_preservation",
                    "structural_integrity", "formatting_fidelity", "language_quality")},
                "evidence": {"faithfulness": "ok"}}

    def test_valid_submission_saves_sheet(self, tree):
        r = client.post("/judge/submit", json=self._valid_payload())
        assert r.status_code == 200
        assert r.json()["ok"] is True
        sheet = json.loads((tree["human"] / "meeting-01.json").read_text(encoding="utf-8"))
        assert sheet["scores"]["faithfulness"] == 4

    def test_unknown_case_404(self):
        r = client.post("/judge/submit", json={"case_id": "nope", "scores": self._valid_payload()["scores"]})
        assert r.status_code == 404

    def test_missing_dimension_422(self):
        payload = self._valid_payload()
        payload["scores"].pop("language_quality")
        r = client.post("/judge/submit", json=payload)
        assert r.status_code == 422
        assert "language_quality" in r.text

    def test_out_of_range_score_422(self):
        payload = self._valid_payload()
        payload["scores"]["faithfulness"] = 9
        r = client.post("/judge/submit", json=payload)
        assert r.status_code == 422

    def test_non_dict_scores_422(self):
        payload = self._valid_payload()
        payload["scores"] = [1, 2, 3]
        r = client.post("/judge/submit", json=payload)
        assert r.status_code == 422


class TestAnalysis:
    def test_analysis_with_both_raters(self, tree):
        r = client.get("/study/analysis")
        assert r.status_code == 200
        body = r.json()
        assert body["overall"]["n_cases"] == 1
        assert body["overall"]["n_judgments"] == 6
        assert body["overall"]["kappa"] == 1.0
        assert body["disagreements"] == []
        assert body["distributions"]["human"]["4"] == 6

    def test_analysis_409_when_raters_missing(self, tree):
        (tree["auto"] / "plan-01.json").unlink()
        r = client.get("/study/analysis")
        assert r.status_code == 409

    def test_scores_endpoint_shape(self, tree):
        r = client.get("/study/scores")
        assert r.status_code == 200
        body = r.json()
        assert set(body["human"]) == {"plan-01"}
        assert set(body["auto"]) == {"plan-01"}


class TestReportEndpoints:
    def test_report_markdown(self):
        r = client.get("/study/report")
        assert r.status_code == 200
        assert "## 1." in r.text
        assert r.headers["content-type"].startswith("text/plain")

    def test_export_docx(self, tree, monkeypatch):
        calls = {}

        def fake_export(self, session_id=None, html=None, fmt="docx", filename=None):
            calls["html"] = html
            calls["fmt"] = fmt
            calls["filename"] = filename
            return b"EXPORTED-DOCX"

        monkeypatch.setattr(SuperDocsClient, "export", fake_export)
        r = client.get("/study/report/export?format=docx")
        assert r.status_code == 200
        assert r.content == b"EXPORTED-DOCX"
        assert "wordprocessingml" in r.headers["content-type"]
        assert "attachment" in r.headers["content-disposition"]
        assert calls["fmt"] == "docx"
        assert "<html>" in (calls["html"] or "")

    def test_export_pdf_media_type(self, monkeypatch):
        monkeypatch.setattr(SuperDocsClient, "export", lambda *a, **k: b"%PDF-1.4")
        r = client.get("/study/report/export?format=pdf")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"

    def test_export_bad_format_rejected(self):
        r = client.get("/study/report/export?format=exe")
        assert r.status_code == 422

    def test_export_error_becomes_502(self, monkeypatch):
        def boom(self, **kwargs):
            raise RuntimeError("export backend down")

        monkeypatch.setattr(SuperDocsClient, "export", boom)
        r = client.get("/study/report/export?format=docx")
        assert r.status_code == 502


class TestRunEndpoints:
    def test_edits_endpoint(self, monkeypatch, tree):
        from app.budget import BudgetGuard

        class FakeRunner:
            def __init__(self):
                self.client = type("C", (), {"budget": BudgetGuard(
                    cap_ops=60, ledger_path=tree["ledger"])})()

            def run_all(self, ids):
                return {"results": [{"case_id": "plan-01", "status": "completed"}], "failed": []}

        monkeypatch.setattr("app.main.EditRunner", FakeRunner)
        r = client.post("/study/edits?case_ids=plan-01")
        assert r.status_code == 200
        body = r.json()
        assert body["summary"]["results"][0]["status"] == "completed"
        assert body["budget"]["cap_ops"] == 60

    def test_auto_judge_endpoint(self, monkeypatch, tree):
        from app.budget import BudgetGuard

        class FakeJudge:
            def __init__(self):
                self.client = type("C", (), {"budget": BudgetGuard(
                    cap_ops=60, ledger_path=tree["ledger"])})()

            def judge_all(self, ids):
                return {"results": [{"case_id": "plan-01", "status": "completed"}], "failed": []}

        monkeypatch.setattr("app.main.AutoJudge", FakeJudge)
        r = client.post("/study/judge/auto")
        assert r.status_code == 200
        assert r.json()["summary"]["results"][0]["status"] == "completed"


class TestConfigGuard:
    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.setattr(config, "API_KEY", "")
        from app.superdocs_client import SuperDocsClient
        with pytest.raises(RuntimeError, match="SUPERDOCS_API_KEY"):
            SuperDocsClient()

    def test_gemini_judge_requires_key(self, monkeypatch):
        monkeypatch.setattr(config, "GEMINI_API_KEY", "")
        from app.judges import GeminiJudge
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            GeminiJudge()