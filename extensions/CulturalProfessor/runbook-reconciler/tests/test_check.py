"""The deterministic checker, against the corpus and against the key.

`test_the_checker_scores_perfectly_against_the_key` is the headline and it is
also the one to be most suspicious of: a perfect score on a corpus written by
the same person who wrote the checker is a weaker claim than the number looks,
and the README says so. What it does establish is that the key — written before
any of this code existed — and the implementation agree completely, including on
the cases planted specifically to be got wrong.

The rest are the unit-level cases behind that number, and the ones worth reading
are the comparisons: a percentage against a fraction, milliseconds against
seconds, a cron schedule against a time of day. Each of those pairs is the same
value written two ways, and reporting any of them as drift would put a false
positive on a page that is correct.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reconciler.check.compare import compare, parse_quantity
from reconciler.check.vertical import load_checks
from reconciler.config import PROJECT_ROOT, Config
from reconciler.measure import load_key, score
from reconciler.register import Register
from reconciler.sweep import Sweep, SweepResult


@pytest.fixture(scope="module")
def swept(tmp_path_factory: pytest.TempPathFactory) -> SweepResult:
    config = Config.load()
    register_path = tmp_path_factory.mktemp("register") / "register.db"
    with Register(register_path) as register:
        return Sweep(config, register).run(mode="test")


# --------------------------------------------------------------- the score --


def test_the_checker_scores_perfectly_against_the_key(swept: SweepResult) -> None:
    scored = score(swept.findings, swept.claims)
    assert scored.misses == [], "the key expects findings the checker did not produce"
    assert scored.false_positives == [], "the checker reported findings the key does not expect"
    assert scored.precision == 1.0
    assert scored.recall == 1.0
    assert scored.cried_wolf == 0.0


def test_nothing_uncheckable_is_reported_as_checked(swept: SweepResult) -> None:
    """Rule 4, scored apart from precision on purpose.

    A miss is a gap in coverage. This is a lie about coverage, and averaging the
    two into one number would let a tool trade the second for the first and come
    out looking better.
    """
    scored = score(swept.findings, swept.claims)
    assert scored.rule_four_violations == []


def test_the_coverage_headline_matches_the_key(swept: SweepResult) -> None:
    key = load_key()["coverage"]
    coverage = swept.coverage
    assert coverage.alerts_total == key["alerts_total"]
    assert coverage.alerts_with_resolving_runbook == key["alerts_with_resolving_runbook"]
    assert coverage.alerts_with_dead_runbook_link == key["alerts_with_dead_runbook_link"]
    assert coverage.alerts_without_runbook_url == key["alerts_without_runbook_url"]
    assert list(coverage.orphan_runbook_pages) == key["orphan_runbook_pages"]
    assert coverage.dead_dashboard_links == key["dead_dashboard_links"]


def test_the_clean_page_produces_nothing(swept: SweepResult) -> None:
    """Page 1008 is entirely correct, and the zero-findings proof rests on it."""
    assert [f for f in swept.findings if f.page_id == "1008" and f.verdict == "contradicts"] == []


# ---------------------------------------------------------- the comparisons --


def test_a_percentage_equals_the_fraction_it_stands_for() -> None:
    """`5%` and `0.05`. Getting this wrong put false positives on two pages."""
    assert compare("numeric", "5%", "0.05") is True
    assert compare("numeric", "5%", "0.10") is False


def test_a_percentage_parses_its_unit_at_end_of_string() -> None:
    """The bug underneath the one above: `\\b` after `%` never matches."""
    assert parse_quantity("5%").unit == "%"
    assert parse_quantity("800ms").unit == "ms"
    assert parse_quantity("30 minutes").unit == "minutes"


def test_milliseconds_compare_against_a_seconds_metric() -> None:
    expr = "histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m])) > 1.2"
    assert compare("numeric", "800ms", "1.2", {"expr": expr}) is False
    assert compare("numeric", "1200ms", "1.2", {"expr": expr}) is True


def test_an_elapsed_threshold_in_minutes_compares_against_seconds() -> None:
    expr = "time() - max(manifest_worker_last_success_timestamp_seconds) > 1800"
    assert compare("numeric", "30 minutes", "1800", {"expr": expr}) is True


def test_a_unit_with_nothing_to_convert_it_against_is_undecidable() -> None:
    """Undecidable, not equal and not different.

    A bare number on one side, a unit on the other, and no expression to say
    what the bare number means. Guessing is how a correct page becomes drift.
    """
    assert compare("numeric", "800ms", "1.2", {"expr": "some_gauge > 1.2"}) is None


def test_a_cron_schedule_compares_against_a_time_of_day() -> None:
    assert compare("clock", "03:00 UTC daily", "cron(0 3 * * ? *)") is True
    assert compare("clock", "02:00 UTC daily", "cron(0 3 * * ? *)") is False


def test_a_window_matches_any_range_selector_in_the_expression() -> None:
    assert compare("window", "30 minute", "", {"ranges": ["30m", "30m"]}) is True
    assert compare("window", "5 minute", "", {"ranges": ["30m"]}) is False


def test_a_retention_in_days_needs_the_rule_to_declare_the_unit() -> None:
    """`backup_retention_period = 14` is a bare number in the file."""
    assert compare("duration", "7 days", "14", {"observed_unit": "days"}) is False
    assert compare("duration", "14 days", "14", {"observed_unit": "days"}) is True
    assert compare("duration", "14 days", "14", {}) is None


# ------------------------------------------------------- the closed world ----


def test_a_missing_ci_job_is_a_contradiction_not_an_unknown(swept: SweepResult) -> None:
    """Every job in every workflow is enumerable, so absence is proof."""
    finding = next(f for f in swept.findings if f.subject == "job:rollback-production")
    assert finding.verdict == "contradicts"
    assert "manual-rollback" in (finding.observed or "")


def test_a_missing_identifier_is_an_unknown_not_a_contradiction(swept: SweepResult) -> None:
    """The other half of the same decision.

    A hyphenated token in a code span might be a resource, a placeholder or an
    example. Absence proves nothing, and calling it a contradiction is the
    cried-wolf rate going up for no information.
    """
    checks = {c.id: c for c in load_checks()}
    assert checks["resource-identifier"].on_missing == "unverifiable"
    assert checks["ci-job"].on_missing == "contradicts"


def test_a_renamed_service_is_resolved_and_reported_as_renamed(swept: SweepResult) -> None:
    finding = next(f for f in swept.findings if f.subject == "workload:tracking-api:name")
    assert finding.verdict == "contradicts"
    assert finding.observed == "tracking-ingest"
    assert "via:former-name" in finding.tags


# --------------------------------------------------------- the orphan rule ---


def test_a_dead_service_yields_one_finding_not_one_per_sentence(swept: SweepResult) -> None:
    page = [f for f in swept.findings if f.page_id == "1005"]
    contradictions = [f for f in page if f.verdict == "contradicts"]
    assert {f.rule_id for f in contradictions} == {
        "orphan-runbook",
        "instructions-to-automation",
    }
    assert all(f.verdict == "unverifiable" for f in page if f not in contradictions)


def test_a_rota_that_does_not_exist_on_an_orphan_page_is_not_a_separate_finding(
    swept: SweepResult,
) -> None:
    """`escalation:Messaging` names no declared rota, and would be a
    contradiction on any live page. On a page about a decommissioned service it
    is one more symptom of the single decision already flagged."""
    finding = next(f for f in swept.findings if f.subject == "escalation:Messaging")
    assert finding.verdict == "unverifiable"


# ------------------------------------------------------------- the rules ----


def test_every_check_names_a_lookup_that_exists() -> None:
    """`config/checks.yaml` is data, so a typo in it is a silent behaviour change."""
    from reconciler.check import lookups

    available = set(lookups.names())
    for check in load_checks():
        assert check.lookup in available, f"{check.id} names unknown lookup {check.lookup!r}"
        assert check.on_missing in ("unverifiable", "contradicts")


def test_the_measurement_file_is_written_and_recomputable(
    swept: SweepResult, tmp_path: Path
) -> None:
    from reconciler.measure import write_raw

    path = write_raw(score(swept.findings, swept.claims), swept.findings, tmp_path / "m.json")
    assert path.is_file()
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["score"]["precision"] == 1.0
    assert payload["method"].startswith("expected.yaml was written before")
    assert len(payload["findings"]) == len(swept.findings)


def test_committed_measurement_matches_a_fresh_run(swept: SweepResult) -> None:
    """The number in docs/ is the number this code produces today.

    A committed measurement that has drifted from the code is worse than no
    measurement, because it looks like evidence.
    """
    import json

    committed = PROJECT_ROOT / "docs" / "measurement.json"
    if not committed.is_file():
        pytest.skip("no committed measurement yet; `rr measure` writes one")
    payload = json.loads(committed.read_text(encoding="utf-8"))
    fresh = score(swept.findings, swept.claims)
    assert payload["score"]["precision"] == pytest.approx(fresh.precision)
    assert payload["score"]["recall"] == pytest.approx(fresh.recall)
    assert payload["score"]["expected"] == fresh.expected


def test_an_alert_whose_name_is_a_prefix_of_another_is_not_reported_documented() -> None:
    """`PaymentsApiHighLatency` is a prefix of `PaymentsApiHighLatencyWarning`.

    A plain `in` test reported the warning as documented by the page that only
    ever names the critical alert, and turned an `orphan-alert` into an
    `unlinked-runbook` — a finding telling the team to annotate their rule with
    a page that does not describe it. Nearly-right is the worst shape for this
    one, because it reads as almost done and is not.
    """
    from reconciler.check.coverage import _page_mentioning

    text = {"1001": "PaymentsApiHighLatency fires when p99 latency stays above 800ms."}

    assert _page_mentioning("PaymentsApiHighLatency", text) == "1001"
    assert _page_mentioning("PaymentsApiHighLatencyWarning", text) is None


def test_a_bounded_match_still_finds_a_name_next_to_punctuation() -> None:
    """The boundary must not cost the ordinary case: a name in a heading, in a
    sentence ending in a full stop, or inside a code span is still the alert
    being documented."""
    from reconciler.check.coverage import _page_mentioning

    for wording in (
        "Runbook: ManifestWorkerStalled",
        "When ManifestWorkerStalled fires, drain the queue.",
        "See `ManifestWorkerStalled`.",
        "ManifestWorkerStalled",
    ):
        assert _page_mentioning("ManifestWorkerStalled", {"1008": wording}) == "1008"


def test_a_placeholder_in_a_command_does_not_condemn_the_whole_page() -> None:
    """The most expensive false positive this tool can produce.

    `kubectl rollout restart deploy/SERVICE_HERE` made `SERVICE_HERE` the claim
    that names the page's subject service. The page-level pass runs *before* the
    per-claim placeholder check ever sees it, so nothing in the estate resolved
    it and the whole page was reported as a runbook for a service that no longer
    exists — every other claim on it marked unverifiable as a consequence. One
    templated command, one condemned page.
    """
    from reconciler.check.vertical import check_page
    from reconciler.config import Config
    from reconciler.estate import Estate
    from reconciler.extract.patterns import extract_claims
    from reconciler.extract.storage import parse

    body = (
        "<h2>Triage</h2>\n<p>The deployment is <code>payments-api</code> in namespace "
        "<code>payments</code>.</p>\n<p>Then run <code>kubectl rollout restart "
        "deploy/SERVICE_HERE</code> against your own service.</p>"
    )
    document = parse(body, page_id="9200")
    findings = check_page("9200", extract_claims(document), Estate.load(Config.load()))

    assert not [f for f in findings if f.rule_id == "orphan-runbook"]
    assert [f for f in findings if f.verdict == "agrees"], "the real claims still get checked"


def test_the_placeholder_conventions_cover_the_four_common_spellings() -> None:
    """And deliberately not bare capitals, which could be a real resource."""
    from reconciler.extract.storage import placeholder_matcher

    matcher = placeholder_matcher()
    for spelling in ("<your-namespace>", "{{ namespace }}", "$NAMESPACE", "SERVICE_HERE"):
        assert matcher.search(spelling), spelling
    for real in ("payments-api", "payments", "manual-rollback"):
        assert not matcher.search(real), real


def test_an_estate_can_add_its_own_placeholder_spelling() -> None:
    """The README's promise that a team "says so in config" had nowhere to go."""
    from reconciler.extract.storage import placeholder_matcher

    assert not placeholder_matcher().search("PLACEHOLDER_ns")
    assert placeholder_matcher((r"PLACEHOLDER_\w+",)).search("PLACEHOLDER_ns")
    # A broken pattern is dropped rather than taking the checker down with it.
    assert placeholder_matcher((r"[unclosed",)).search("<your-namespace>")
