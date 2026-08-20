"""Judge tests: GeminiJudge against a mocked HTTP layer, AutoJudge against a
scripted chat client, and the prompt/clip building blocks."""

import json

import pytest

from app.judges import AutoJudge, GeminiJudge, _clip, build_judge_prompt, load_score_sheets
from app.rubric import DIMENSION_IDS, load_rubric

from conftest import DIMENSIONS


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload else "")

    def json(self):
        return self._payload


def gemini_payload(content, usage=None):
    return {
        "choices": [{"message": {"content": content}}],
        "usage": usage or {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


def _case():
    return {"case_id": "plan-01", "difficulty": "easy",
            "instruction": "Add the missing owner."}


class TestGeminiJudge:
    def test_success_writes_sheet_and_usage(self, tree, monkeypatch):
        scores = {d: 4 for d in DIMENSIONS}
        content = json.dumps({"scores": scores, "evidence": {d: f"ev:{d}" for d in DIMENSIONS}})
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["body"] = json
            return FakeResponse(200, gemini_payload(content))

        monkeypatch.setattr("app.judges.requests.post", fake_post)
        out = GeminiJudge().judge_case(_case())

        assert out["status"] == "completed"
        assert out["scores"] == scores
        sheet = json.loads((tree["auto"] / "plan-01.json").read_text(encoding="utf-8"))
        assert sheet["provider"] == "gemini"
        assert sheet["model"] == "gemini-3.6-flash"
        assert sheet["scores"] == scores
        assert sheet["evidence"]["faithfulness"] == "ev:faithfulness"
        usage = json.loads((tree["gemini_ledger"]).read_text(encoding="utf-8").splitlines()[0])
        assert usage["total_tokens"] == 150
        assert usage["case_id"] == "plan-01"

    def test_request_shape(self, tree, monkeypatch):
        captured = {}
        content = json.dumps({"scores": {d: 4 for d in DIMENSIONS}, "evidence": {}})

        def fake_post(url, headers=None, json=None, timeout=None):
            captured.update(url=url, headers=headers, body=json)
            return FakeResponse(200, gemini_payload(content))

        monkeypatch.setattr("app.judges.requests.post", fake_post)
        GeminiJudge().judge_case(_case())

        assert "chat/completions" in captured["url"]
        assert captured["headers"]["Authorization"] == "Bearer test-gemini-key"
        assert captured["body"]["temperature"] == 0
        assert captured["body"]["response_format"] == {"type": "json_object"}
        assert captured["body"]["messages"][0]["role"] == "user"
        assert "INSTRUCTION: Add the missing owner." in captured["body"]["messages"][0]["content"]

    def test_no_edited_material_fails_gracefully(self, tree):
        out = GeminiJudge().judge_case({"case_id": "meeting-01", "difficulty": "medium",
                                        "instruction": "x"})
        assert out["status"] == "failed"
        assert "no edited text" in out["error"]

    def test_unparseable_response_fails(self, tree, monkeypatch):
        def fake_post(url, headers=None, json=None, timeout=None):
            return FakeResponse(200, gemini_payload("I am not JSON at all"))

        monkeypatch.setattr("app.judges.requests.post", fake_post)
        before = (tree["auto"] / "plan-01.json").read_text(encoding="utf-8")  # fixture sheet
        out = GeminiJudge().judge_case(_case())
        assert out["status"] == "failed"
        assert "no parseable JSON" in out["error"]
        # the pre-existing fixture sheet must be untouched
        assert (tree["auto"] / "plan-01.json").read_text(encoding="utf-8") == before

    def test_invalid_scores_fail(self, tree, monkeypatch):
        content = json.dumps({"scores": {d: 4 for d in DIMENSIONS[:-1]} | {"language_quality": 9},
                              "evidence": {}})

        def fake_post(url, headers=None, json=None, timeout=None):
            return FakeResponse(200, gemini_payload(content))

        monkeypatch.setattr("app.judges.requests.post", fake_post)
        out = GeminiJudge().judge_case(_case())
        assert out["status"] == "failed"
        assert "invalid scores" in out["error"]

    def test_http_error_fails(self, tree, monkeypatch):
        def fake_post(url, headers=None, json=None, timeout=None):
            return FakeResponse(429, text="rate limited")

        monkeypatch.setattr("app.judges.requests.post", fake_post)
        out = GeminiJudge().judge_case(_case())
        assert out["status"] == "failed"
        assert "429" in out["error"]

    def test_network_error_fails(self, tree, monkeypatch):
        import requests as requests_mod

        def fake_post(url, headers=None, json=None, timeout=None):
            raise requests_mod.exceptions.ConnectionError("connection refused")

        monkeypatch.setattr("app.judges.requests.post", fake_post)
        out = GeminiJudge().judge_case(_case())
        assert out["status"] == "failed"
        assert "gemini request failed" in out["error"]

    def test_judge_all_filters(self, tree, monkeypatch):
        content = json.dumps({"scores": {d: 4 for d in DIMENSIONS}, "evidence": {}})
        monkeypatch.setattr("app.judges.requests.post",
                            lambda *a, **k: FakeResponse(200, gemini_payload(content)))
        summary = GeminiJudge().judge_all(["plan-01"])
        assert len(summary["results"]) == 1
        assert summary["results"][0]["case_id"] == "plan-01"
        assert summary["failed"] == []


class FakeChatClient:
    def __init__(self, responses, budget=None, cap_ops=60, ledger_path=None):
        from app.budget import BudgetGuard
        self.responses = list(responses)
        self.budget = budget or BudgetGuard(cap_ops=cap_ops, ledger_path=ledger_path)

    def chat_sync(self, session_id, message, model_tier=None, thinking_depth=None):
        from app.budget import BudgetExceeded
        self.budget.guard(1)
        if not self.responses:
            raise RuntimeError("no scripted responses left")
        return self.responses.pop(0)


class TestAutoJudge:
    def test_first_try_json(self, tree, tmp_path):
        content = json.dumps({"scores": {d: 4 for d in DIMENSIONS}, "evidence": {}})
        client = FakeChatClient([{"response": content}], ledger_path=tmp_path / "ledger.jsonl")
        out = AutoJudge(client=client).judge_case(_case())
        assert out["status"] == "completed"
        assert out["attempts"] == 1
        assert (tree["auto"] / "plan-01.json").exists()

    def test_retries_until_json(self, tree, tmp_path):
        content = json.dumps({"scores": {d: 4 for d in DIMENSIONS}, "evidence": {}})
        client = FakeChatClient([
            {"response": "Done."},
            {"response": "I'll score the edit now."},
            {"response": f"Here: {content}"},
        ], ledger_path=tmp_path / "ledger.jsonl")
        out = AutoJudge(client=client).judge_case(_case())
        assert out["status"] == "completed"
        assert out["attempts"] == 3

    def test_gives_up_after_max_attempts(self, tree, tmp_path):
        client = FakeChatClient([{"response": "Done."}, {"response": "Done."}, {"response": "Done."}],
                                ledger_path=tmp_path / "ledger.jsonl")
        before = (tree["auto"] / "plan-01.json").read_text(encoding="utf-8")  # fixture sheet
        out = AutoJudge(client=client, max_attempts=3).judge_case(_case())
        assert out["status"] == "failed"
        assert "no JSON after 3 attempts" in out["error"]
        assert (tree["auto"] / "plan-01.json").read_text(encoding="utf-8") == before

    def test_budget_exceeded_fails(self, tree, tmp_path):
        client = FakeChatClient([{"response": "x"}], cap_ops=0, ledger_path=tmp_path / "ledger.jsonl")
        out = AutoJudge(client=client).judge_case(_case())
        assert out["status"] == "failed"
        assert "budget" in out["error"].lower()


class TestClip:
    def test_short_text_unchanged(self):
        text = "short"
        assert _clip(text) == text

    def test_long_text_keeps_head_tail_and_harness_note(self):
        text = "A" * 3000 + "B" * 2000 + "C" * 1000  # 6000 > 4000
        out = _clip(text, limit=4000)
        assert "[HARNESS NOTE" in out
        assert out.startswith("A" * 2400)  # head = first 60%
        assert out.endswith("C" * 1000)    # tail = last 40%
        assert "B" * 2000 not in out       # middle removed

    def test_empty_and_whitespace(self):
        assert _clip("") == ""
        assert _clip("   ") == ""

    def test_limit_respected(self):
        text = "x" * 5000
        out = _clip(text, limit=1000)
        assert len(out) < 2000


class TestJudgePrompt:
    def test_contains_instruction_anchors_and_harness_note(self, tree):
        rubric = load_rubric()
        prompt = build_judge_prompt(
            {"case_id": "plan-01", "instruction": "Add the missing owner."},
            "SOURCE TEXT", "EDITED TEXT", rubric)
        assert "INSTRUCTION: Add the missing owner." in prompt
        for d in rubric["dimensions"]:
            assert d["id"] in prompt
            assert d["anchors"]["1"][:40] in prompt
        assert "HARNESS NOTE" in prompt
        assert prompt.index("SOURCE:") < prompt.index("EDITED:")

    def test_prompt_requests_json_only(self, tree):
        rubric = load_rubric()
        prompt = build_judge_prompt({"case_id": "x", "instruction": "i"}, "s", "e", rubric)
        assert "JSON ONLY" in prompt
        assert '"scores"' in prompt and '"evidence"' in prompt


class TestSheetStorage:
    def test_save_human_scores_requires_all_dimensions(self, tree):
        from app.judges import save_human_scores
        with pytest.raises(ValueError):
            save_human_scores("plan-01", {"faithfulness": 4}, {})
        with pytest.raises(ValueError):
            save_human_scores("plan-01", {d: 0 for d in DIMENSION_IDS}, {})
        sheet = save_human_scores("plan-01", {d: 3 for d in DIMENSION_IDS}, {})
        assert sheet["scores"] == {d: 3 for d in DIMENSION_IDS}

    def test_boolean_is_not_a_valid_score(self):
        from app.rubric import valid_score
        assert not valid_score(True)
        assert not valid_score(4.0)
        assert valid_score(4)