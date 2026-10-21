"""Tests for the verdict cache.

The cache is the reason the tool is fast on files nobody touched, so it has to be provably correct
about when an old answer still applies — and provably unwilling to remember an answer that was
never really reached.
"""

from __future__ import annotations

from docs_lint.cache import VerdictCache
from docs_lint.model import Anchor, FileResult, Finding, Severity, Verdict

DOC = b"# Title\n\nWe utilise the API.\n"


def cache(tmp_path, fingerprint="fp1") -> VerdictCache:
    return VerdictCache(tmp_path, config_fingerprint=fingerprint)


def finding(path="a.md") -> Finding:
    return Finding(
        rule_id="banned-terms",
        severity=Severity.ERROR,
        message="Avoid 'utilise'",
        anchor=Anchor(path=path, start_line=3, end_line=3, start_char=10, end_char=17),
        replacement="use",
    )


def result(verdict: Verdict, path="a.md", findings=()) -> FileResult:
    return FileResult(path=path, verdict=verdict, findings=findings)


# -- hits ---------------------------------------------------------------------------


def test_unchanged_content_and_config_hits_the_cache(tmp_path):
    store = cache(tmp_path)
    store.put(result(Verdict.clean(checks_run=("local", "superdocs"))), DOC)

    hit = store.get("a.md", DOC)
    assert hit is not None
    assert hit.from_cache
    assert hit.verdict.checks_run == ("local", "superdocs")
    assert store.hits == 1


def test_findings_survive_the_round_trip(tmp_path):
    store = cache(tmp_path)
    store.put(result(Verdict.findings(checks_run=("local",)), findings=(finding(),)), DOC)

    hit = store.get("a.md", DOC)
    assert hit is not None
    assert [f.rule_id for f in hit.findings] == ["banned-terms"]
    assert hit.findings[0].replacement == "use"


# -- misses that matter -------------------------------------------------------------


def test_edited_content_misses(tmp_path):
    store = cache(tmp_path)
    store.put(result(Verdict.clean(checks_run=("local",))), DOC)
    assert store.get("a.md", DOC + b"\nmore text\n") is None


def test_changed_configuration_misses(tmp_path):
    """A document judged under the old rules has not been judged under the new ones."""
    cache(tmp_path, "fp1").put(result(Verdict.clean(checks_run=("local",))), DOC)
    assert cache(tmp_path, "fp2").get("a.md", DOC) is None


def test_an_edited_style_guide_misses_because_it_changes_the_fingerprint(tmp_path):
    """The style guide hash is folded into the config fingerprint, so this follows for free."""
    cache(tmp_path, "fp-guide-v1").put(result(Verdict.clean(checks_run=("superdocs",))), DOC)
    assert cache(tmp_path, "fp-guide-v2").get("a.md", DOC) is None


# -- verdicts that must never be remembered -----------------------------------------


def test_a_failed_verdict_is_not_cached(tmp_path):
    """A transient outage must not become this document's permanent verdict."""
    store = cache(tmp_path)
    store.put(result(Verdict.failed("SuperDocs unreachable")), DOC)
    assert store.get("a.md", DOC) is None


def test_a_skipped_verdict_is_not_cached(tmp_path):
    store = cache(tmp_path)
    store.put(result(Verdict.skipped("over budget")), DOC)
    assert store.get("a.md", DOC) is None


# -- robustness ---------------------------------------------------------------------


def test_a_corrupt_entry_is_a_miss_not_a_crash(tmp_path):
    store = cache(tmp_path)
    store.put(result(Verdict.clean(checks_run=("local",))), DOC)

    entry = next(store.dir.rglob("*.json"))
    entry.write_text("{ truncated")

    assert store.get("a.md", DOC) is None
    assert not entry.exists(), "a corrupt entry is discarded rather than re-read forever"


def test_a_disabled_cache_never_answers(tmp_path):
    store = VerdictCache(tmp_path, config_fingerprint="fp1", enabled=False)
    store.put(result(Verdict.clean(checks_run=("local",))), DOC)
    assert store.get("a.md", DOC) is None


def test_clearing_removes_every_entry(tmp_path):
    store = cache(tmp_path)
    store.put(result(Verdict.clean(checks_run=("local",)), path="a.md"), DOC)
    store.put(result(Verdict.clean(checks_run=("local",)), path="b.md"), DOC + b"x")

    assert store.clear() == 2
    assert store.get("a.md", DOC) is None


def test_entries_are_sharded_so_a_big_repository_stays_navigable(tmp_path):
    store = cache(tmp_path)
    for index in range(5):
        store.put(result(Verdict.clean(checks_run=("local",))), DOC + str(index).encode())

    shards = {p.parent.name for p in store.dir.rglob("*.json")}
    assert all(len(shard) == 2 for shard in shards)
