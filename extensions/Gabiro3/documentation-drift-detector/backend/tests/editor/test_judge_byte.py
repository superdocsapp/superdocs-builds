import pytest
from agents.editor.judge_byte import JudgeByte


class TestJudgeByte:
    def test_phase_a_all_target_chunks_ok(self):
        pending = [
            {"chunk_id": "c001", "html_diff": "<div>diff</div>"},
        ]
        result = JudgeByte.phase_a(pending, {"c001"})
        assert result["ok"] is True

    def test_phase_a_stray_chunk_rejected(self):
        pending = [
            {"chunk_id": "c002", "html_diff": "<div>wrong</div>"},
        ]
        result = JudgeByte.phase_a(pending, {"c001"})
        assert result["ok"] is False
        assert "c002" in result["reason"]

    def test_phase_a_empty_changes_ok(self):
        result = JudgeByte.phase_a([], {"c001"})
        assert result["ok"] is True

    def test_phase_b_untouched_chunks_identical(self):
        pre = {"c001": "hash_aaa", "c002": "hash_bbb", "c003": "hash_ccc"}
        post = {"c001": "hash_new", "c002": "hash_bbb", "c003": "hash_ccc"}
        result = JudgeByte.phase_b(post, pre, target_id="c001")
        assert result["ok"] is True

    def test_phase_b_violation_detected(self):
        pre = {"c001": "hash_aaa", "c002": "hash_bbb"}
        post = {"c001": "hash_new", "c002": "hash_corrupted"}
        result = JudgeByte.phase_b(post, pre, target_id="c001")
        assert result["ok"] is False
        assert "c002" in result["reason"]

    def test_phase_b_target_changed_is_allowed(self):
        pre = {"c001": "hash_old"}
        post = {"c001": "hash_new"}
        result = JudgeByte.phase_b(post, pre, target_id="c001")
        assert result["ok"] is True

    def test_phase_b_new_chunk_in_post_is_ignored(self):
        pre = {"c001": "hash_old"}
        post = {"c001": "hash_new", "c002": "hash_newest"}
        result = JudgeByte.phase_b(post, pre, target_id="c001")
        assert result["ok"] is True

    def test_hash_document_snapshot(self):
        chunks = [
            {"chunk_id": "c001", "content_hash": "abc"},
            {"chunk_id": "c002", "content_hash": "def"},
        ]
        snap = JudgeByte.hash_document_snapshot(chunks)
        assert snap == {"c001": "abc", "c002": "def"}