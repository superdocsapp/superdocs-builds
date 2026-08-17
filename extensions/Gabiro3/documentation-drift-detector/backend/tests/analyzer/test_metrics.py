import pytest

from agents.analyzer.metrics import (
    Metrics,
    chunk_contains,
    compute_metrics,
    normalize,
)


class TestChunkContains:
    def test_finds_value_across_inline_tags(self):
        assert chunk_contains("<p>run <code>npm</code> install</p>", "npm")

    def test_is_case_insensitive(self):
        assert chunk_contains("<p>Port 3000</p>", "port 3000")

    def test_collapses_whitespace(self):
        assert chunk_contains("<p>port\n  3000</p>", "port 3000")

    def test_rejects_absent_value(self):
        assert not chunk_contains("<p>run pnpm install</p>", "npm install")

    def test_empty_value_is_never_contained(self):
        assert not chunk_contains("<p>anything</p>", "")


class TestComputeMetrics:
    FACTS = [
        {"id": "f1", "type": "renamed", "old_value": "npm", "new_value": "pnpm"},
    ]
    CHUNKS = [
        {"chunk_id": "c1", "html": "<p>run npm install</p>"},   # ground-truth positive
        {"chunk_id": "c2", "html": "<p>run npm test</p>"},      # ground-truth positive
        {"chunk_id": "c3", "html": "<p>unrelated prose</p>"},   # negative
    ]

    def _finding(self, chunk, state="CONFIRMED_DRIFT", fact="f1"):
        return {
            "change_fact_id": fact,
            "chunk_id": chunk,
            "evidence_chunk_id": chunk,
            "state": state,
        }

    def test_perfect_localization(self):
        m = compute_metrics(
            self.FACTS, self.CHUNKS, [self._finding("c1"), self._finding("c2")]
        )
        assert (m.true_positives, m.false_positives, m.false_negatives) == (2, 0, 0)
        assert m.precision == 1.0 and m.recall == 1.0 and m.f1 == 1.0

    def test_wrong_chunk_is_a_false_positive(self):
        # Names a chunk that does NOT contain the stale value.
        m = compute_metrics(self.FACTS, self.CHUNKS, [self._finding("c3")])
        assert m.false_positives == 1
        assert m.true_positives == 0
        assert m.precision == 0.0

    def test_missed_chunk_is_a_false_negative(self):
        m = compute_metrics(self.FACTS, self.CHUNKS, [self._finding("c1")])
        assert m.true_positives == 1
        assert m.false_negatives == 1
        assert m.recall == 0.5

    def test_unknown_is_not_a_false_negative(self):
        """An honest abstention must not be scored as a miss — penalising it
        would train the system to guess."""
        findings = [self._finding("c1"), self._finding("c2", state="UNKNOWN")]
        m = compute_metrics(self.FACTS, self.CHUNKS, findings)
        assert m.unknown == 1
        assert m.unknown_rate == 0.5
        assert m.coverage == 0.5
        # c2 is still ground-truth positive and unpredicted => FN, but the
        # UNKNOWN finding itself contributes no FP.
        assert m.false_positives == 0

    def test_accuracy_includes_true_negatives(self):
        m = compute_metrics(
            self.FACTS, self.CHUNKS, [self._finding("c1"), self._finding("c2")]
        )
        assert m.true_negatives == 1  # c3
        assert m.accuracy == 1.0

    def test_non_literal_fact_is_excluded_not_assumed_correct(self):
        facts = [{"id": "f9", "type": "added", "old_value": None, "new_value": "x"}]
        m = compute_metrics(facts, self.CHUNKS, [])
        assert m.scored_facts == 0
        assert m.unscorable_facts == 1
        assert any("not decidable in code" in l for l in m.limitations)

    def test_undefined_scores_are_none_not_zero(self):
        """None means 'undefined'; 0.0 would be a false claim of total failure."""
        m = compute_metrics([], self.CHUNKS, [])
        assert m.precision is None and m.recall is None and m.accuracy is None

    def test_method_is_stated(self):
        m = compute_metrics(self.FACTS, self.CHUNKS, [self._finding("c1")])
        assert "old_value occurs in the chunk" in m.method

    def test_findings_for_other_facts_do_not_leak(self):
        m = compute_metrics(
            self.FACTS, self.CHUNKS, [self._finding("c3", fact="other-fact")]
        )
        # Belongs to a different fact, so it is neither TP nor FP here.
        assert m.false_positives == 0
        assert m.true_positives == 0

    def test_serialises_to_dict(self):
        m = compute_metrics(self.FACTS, self.CHUNKS, [self._finding("c1")])
        d = m.to_dict()
        assert d["true_positives"] == 1 and "method" in d


class TestTokenBoundaryMatching:
    """'npm' occurs inside 'pnpm'. Substring matching would score a correctly
    migrated document as still drifted, corrupting the ground truth."""

    def test_npm_does_not_match_inside_pnpm(self):
        assert not chunk_contains("<p>run pnpm install</p>", "npm")

    def test_npm_matches_standalone(self):
        assert chunk_contains("<p>run npm install</p>", "npm")

    def test_number_does_not_match_inside_longer_number(self):
        assert not chunk_contains("<p>port 13000</p>", "3000")

    def test_number_matches_standalone(self):
        assert chunk_contains("<p>port 3000 default</p>", "3000")

    def test_hyphenated_neighbour_does_not_match(self):
        assert not chunk_contains("<p>use npm-check here</p>", "npm")

    def test_path_value_matches(self):
        assert chunk_contains("<p>GET /healthz returns 200</p>", "/healthz")

    def test_multiword_value_matches(self):
        assert chunk_contains("<p>expire after 24 hours today</p>", "24 hours")

    def test_punctuation_boundary_matches(self):
        assert chunk_contains("<p>run <code>npm</code>.</p>", "npm")


class TestPartialDetectionIsReported:
    """The Finder emits one finding per drifted chunk, so flagging only one
    of several drifted chunks is genuine under-detection. It must be counted
    against recall and described as a real miss, not excused as an artefact."""

    FACTS = [{"id": "f1", "type": "renamed", "old_value": "npm", "new_value": "pnpm"}]
    CHUNKS = [
        {"chunk_id": "c1", "html": "<p>npm install</p>"},
        {"chunk_id": "c2", "html": "<p>npm test</p>"},
        {"chunk_id": "c3", "html": "<p>npm run build</p>"},
    ]

    def test_reports_partial_detection_as_real_misses(self):
        findings = [{
            "change_fact_id": "f1", "chunk_id": "c1",
            "evidence_chunk_id": "c1", "state": "CONFIRMED_DRIFT",
        }]
        m = compute_metrics(self.FACTS, self.CHUNKS, findings)
        assert m.true_positives == 1
        assert m.false_negatives == 2
        assert any("real misses" in l for l in m.limitations)

    def test_no_note_when_the_only_drifted_chunk_is_found(self):
        chunks = [{"chunk_id": "c1", "html": "<p>npm install</p>"},
                  {"chunk_id": "c2", "html": "<p>nothing here</p>"}]
        findings = [{
            "change_fact_id": "f1", "chunk_id": "c1",
            "evidence_chunk_id": "c1", "state": "CONFIRMED_DRIFT",
        }]
        m = compute_metrics(self.FACTS, chunks, findings)
        assert m.recall == 1.0
        assert not any("real misses" in l for l in m.limitations)
