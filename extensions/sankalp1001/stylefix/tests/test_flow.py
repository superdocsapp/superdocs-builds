"""End-to-end flow tests with no API key and no network.

These are the tests that matter for the card: that the guard actually stands between
a proposal and the document, that swapping the guide changes behaviour with no code
change, and that an already-compliant document produces an honest no-op.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from fake import FakeClient  # noqa: E402
from stylefix.batch import StoppingRule, lint_batch, sample  # noqa: E402
from stylefix.lint import lint_document  # noqa: E402

HOUSE = ROOT / "styleguides" / "house-product-style.md"
PLAIN = ROOT / "styleguides" / "plain-english-public.md"

PAGE = (
    "<h1>Configure the webhook</h1>"
    "<p>In order to start the service, please click Save.</p>"
    "<pre><code>client.initiate(please=True)</code></pre>"
    "<table><tr><td>utilize the cache</td></tr></table>"
)


def _doc(tmp_path):
    p = tmp_path / "page.md"
    p.write_text("placeholder", encoding="utf-8")
    return p


def test_prose_fix_is_applied_and_code_sample_is_refused(tmp_path):
    client = FakeClient(
        html=PAGE,
        proposals={"house": [
            {"change_id": "c1", "rule_id": "no-filler",
             "original": "In order to", "replacement": "To"},
            {"change_id": "c2", "rule_id": "no-please",
             "original": "client.initiate(please=True)",
             "replacement": "client.start()"},
            {"change_id": "c3", "rule_id": "plain-verbs",
             "original": "utilize the cache", "replacement": "use the cache"},
        ]},
    )
    result = lint_document(client, _doc(tmp_path), HOUSE, "s1", apply=True,
                           export_format="docx")

    applied = {f.change.change_id for f in result.applied}
    refused = {f.change.change_id: f.verdict.reason for f in result.dropped}

    assert applied == {"c1"}, "only the prose violation should be applied"
    assert "protected" in refused["c2"], "code sample must be refused"
    assert "protected" in refused["c3"], "table cell must be refused"
    # No feedback on denials: it sends the job back round the revision loop and the
    # denied change returns under a new id (bug log, 2026-08-19). The guard's reason
    # is kept locally instead.
    assert client.approvals == [("c1", True, None),
                                ("c2", False, None),
                                ("c3", False, None)]
    assert client.exports == ["docx"]


def test_swapping_the_guide_changes_behaviour_with_no_code_change(tmp_path):
    """The card's headline criterion, asserted rather than claimed."""
    proposals = {
        "house": [{"change_id": "h1", "rule_id": "ui-verbs",
                   "original": "click Save", "replacement": "select Save"}],
        "plain": [{"change_id": "p1", "rule_id": "no-contractions",
                   "original": "please click Save", "replacement": "please click Save."},
                  {"change_id": "p2", "rule_id": "short-sentences",
                   "original": "In order to", "replacement": "To"}],
    }
    doc = _doc(tmp_path)

    house = lint_document(FakeClient(html=PAGE, proposals=proposals), doc, HOUSE, "s1")
    plain = lint_document(FakeClient(html=PAGE, proposals=proposals), doc, PLAIN, "s2")

    assert {f.rule_id for f in house.findings} == {"ui-verbs"}
    assert {f.rule_id for f in plain.findings} == {"no-contractions", "short-sentences"}


def test_no_changes_proposed_is_reported_without_claiming_compliance(tmp_path):
    """`clean` means the model proposed nothing. It must not be read as proof the
    document satisfies the guide - observed 2026-08-19, the same page yielded three
    changes in one run and none in the next."""
    client = FakeClient(html="<p>Use the cache.</p>", proposals={"house": []})
    result = lint_document(client, _doc(tmp_path), HOUSE, "s1", apply=True,
                           export_format=None)
    assert result.clean
    assert client.approvals == [], "nothing to approve"


def test_export_happens_even_when_no_fix_applied(tmp_path):
    """Exports are free and the caller asked for a file; skipping it silently would
    leave them without the output they requested."""
    client = FakeClient(html="<p>Use the cache.</p>", proposals={"house": []})
    lint_document(client, _doc(tmp_path), HOUSE, "s1", apply=True, export_format="docx")
    assert client.exports == ["docx"]


def test_noop_change_is_refused_not_applied(tmp_path):
    """A 'fix' identical to the original is a bluff, not a fix."""
    client = FakeClient(html="<p>use the cache</p>", proposals={"house": [
        {"change_id": "n1", "rule_id": "plain-verbs",
         "original": "use the cache", "replacement": "use the cache"}]})
    result = lint_document(client, _doc(tmp_path), HOUSE, "s1", apply=True)
    assert not result.applied
    assert "no-op" in result.dropped[0].verdict.reason


def test_unreadable_response_raises_rather_than_reporting_clean(tmp_path):
    from stylefix.parsing import UnreadableProposal

    class Broken(FakeClient):
        def chat(self, session_id, message, **options):
            return {"unexpected": "shape"}

    with pytest.raises(UnreadableProposal):
        lint_document(Broken(html=PAGE), _doc(tmp_path), HOUSE, "s1")


def test_batch_profile_ranks_most_broken_rule_first(tmp_path):
    for i in range(3):
        (tmp_path / f"p{i}.md").write_text("x", encoding="utf-8")
    client = FakeClient(html="<p>In order to run, utilize this.</p>", proposals={
        "house": [
            {"change_id": "a", "rule_id": "no-filler",
             "original": "In order to", "replacement": "To"},
            {"change_id": "b", "rule_id": "plain-verbs",
             "original": "utilize", "replacement": "use"},
        ]})
    report = lint_batch(client, sorted(tmp_path.glob("*.md")), HOUSE, "b")
    profile = dict((r, found) for r, found, _ in report.profile())
    assert profile == {"no-filler": 3, "plain-verbs": 3}
    assert "no violations" not in report.render().lower()


def test_stopping_rule_halts_the_run_and_says_why(tmp_path):
    for i in range(10):
        (tmp_path / f"p{i}.md").write_text("x", encoding="utf-8")
    client = FakeClient(html="<p>ok</p>", proposals={"house": []})
    report = lint_batch(client, sorted(tmp_path.glob("*.md")), HOUSE, "b",
                        stopping=StoppingRule(max_operations=3))
    assert report.stopped_because and "budget" in report.stopped_because
    assert report.skipped, "unattempted documents must be named, not silently dropped"


def test_sample_is_deterministic():
    paths = [Path(f"d/{i}.md") for i in range(20)]
    assert sample(paths, 5) == sample(paths, 5)
    assert len(sample(paths, 5)) == 5
    assert sample(paths, None) == sorted(paths)


def test_guide_readiness_is_waited_for_before_linting(tmp_path):
    """Attachments process asynchronously. Linting before the guide is loaded would
    return few or no violations and report a clean document — a silent falsification
    of the one claim this build rests on."""
    client = FakeClient(html=PAGE, proposals={"house": []})
    lint_document(client, _doc(tmp_path), HOUSE, "s1")
    assert client.readiness_checks == 1


def test_chunk_scope_rescues_a_repeated_phrase(tmp_path):
    """Without chunk scope a phrase appearing twice is refused as ambiguous, which
    would drop most word-level fixes on a real page."""
    page = "<p>click Save to continue</p><p>click Save to finish</p>"
    change = {"change_id": "c1", "rule_id": "ui-verbs", "chunk_id": "k2",
              "original": "click Save", "replacement": "select Save"}

    unscoped = FakeClient(html=page, proposals={"house": [change]})
    assert not lint_document(unscoped, _doc(tmp_path), HOUSE, "s1").applied

    class Chunked(FakeClient):
        def upload_document(self, path, session_id):
            return {"html": page,
                    "chunks": [{"chunk_id": "k1", "html": "<p>click Save to continue</p>"},
                               {"chunk_id": "k2", "html": "<p>click Save to finish</p>"}]}

    scoped = lint_document(Chunked(html=page, proposals={"house": [change]}),
                           _doc(tmp_path), HOUSE, "s1")
    assert len(scoped.applied) == 1
