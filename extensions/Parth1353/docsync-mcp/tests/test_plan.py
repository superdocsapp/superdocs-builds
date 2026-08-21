"""Planning: what moved, who carries it, and whether it is safe to say so."""

from __future__ import annotations

from pathlib import Path

import pytest

from docsync.facts import WorkingTree, read_facts
from docsync.plan import (
    ANCHOR_LITERAL,
    ANCHOR_UNANCHORED,
    ANCHOR_WEAK,
    AUDIT_PROSE,
    AUDIT_WEAK,
    audit,
    body_of,
    build_plan,
    content_hash,
    diff_tables,
    mask_structure,
    occurrences,
    split_front_matter,
)
from docsync.registry import Registry
from tests.conftest import edit_file

RETRY = "src/provisioning/retry.py"
CONFIG = "src/provisioning/config.py"
API = "src/provisioning/api.py"

ADR = "docs/adr/0007-retry-policy.md"
RUNBOOK = "docs/runbook-circuit-activation.md"
SPEC = "docs/spec-provisioning-api.md"
SLA = "docs/sla-summary.md"


def tables(repo: Path, changes: list[tuple[str, str, str]]):
    """Before and after fact tables, with `changes` applied in between."""
    registry = Registry.load(repo)
    before = read_facts(registry, WorkingTree(repo))
    for relpath, old, new in changes:
        edit_file(repo, relpath, old, new)
    after = read_facts(registry, WorkingTree(repo))
    return registry, before, after


class TestOccurrences:
    @pytest.mark.parametrize(
        "haystack,needle,expected",
        [
            # A value at the end of a sentence must still anchor. Treating the
            # full stop as part of the token silently demoted every such fact
            # to prose-only, which was the first real bug this found.
            ("the call is given 30 seconds.", "30 seconds", 1),
            ("given 30 seconds, then stop", "30 seconds", 1),
            ("(30 seconds)", "30 seconds", 1),
            ("| 15 minutes |", "15 minutes", 1),
            ("uptime is 99.95%.", "99.95%", 1),
            # ...but a decimal must not.
            ("a 300 second wait", "30", 0),
            ("version 1.30 shipped", "30", 0),
            ("waits 30.5 seconds", "30", 0),
            ("MAX_ATTEMPTS_2", "MAX_ATTEMPTS", 0),
            # A route is a prefix of a longer route. Left alone, a removed
            # endpoint verifies as removed while its sibling still lists it.
            ("POST /v1/circuits/{id}/provision", "POST /v1/circuits", 0),
            ("| POST /v1/circuits |", "POST /v1/circuits", 1),
            ("GET /v1/circuits/{circuit_id}/status", "GET /v1/circuits/{circuit_id}", 0),
            ("/api/v1/circuits", "/v1/circuits", 0),
            ("topic provisioning.dead-letter.", "provisioning.dead-letter", 1),
            ("topic provisioning.dead-letter-2", "provisioning.dead-letter", 0),
            ("30 and 30 and 30", "30", 3),
            ("nothing here", "", 0),
        ],
    )
    def test_token_boundaries(self, haystack, needle, expected):
        assert occurrences(haystack, needle) == expected


class TestStructureMasking:
    @pytest.mark.parametrize(
        "text",
        [
            "3. **Has it dead-lettered?**",
            "   3. nested list item",
            "## 3. Escalation",
            "3) paren style",
        ],
    )
    def test_list_and_section_numbers_are_not_anchors(self, text):
        # A runbook whose third check is numbered "3." contains the digit once,
        # and it is document structure. Anchoring on it would send an
        # instruction whose most obvious reading is "renumber this list".
        assert occurrences(mask_structure(text), "3") == 0

    def test_a_real_value_survives_masking(self):
        assert occurrences(mask_structure("we retry 3 times"), "3") == 1

    def test_masking_preserves_length(self):
        # Offsets elsewhere in the document must not shift.
        text = "10. item\n"
        assert len(mask_structure(text)) == len(text)


class TestFrontMatter:
    def test_split_returns_both_halves(self):
        text = "---\ntitle: X\ndocsync:\n  covers: [a]\n---\n\n# Body\n"
        front, body = split_front_matter(text)
        assert front.startswith("---") and "covers" in front
        assert body.strip() == "# Body"

    def test_no_front_matter(self):
        assert split_front_matter("# Body\n") == ("", "# Body\n")

    def test_body_excludes_the_declaration(self, repo: Path):
        text = (repo / ADR).read_text()
        assert "covers" in text
        assert "covers" not in body_of(text)


class TestDiff:
    def test_detects_a_scalar_move(self, repo: Path):
        _, before, after = tables(repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")])
        changes = diff_tables(before, after)
        assert [c.key for c in changes] == ["retry.max_attempts"]
        assert (changes[0].before_text, changes[0].after_text) == ("3", "5")

    def test_a_rendering_equal_change_is_not_a_change(self, repo: Path):
        # 30 and 30.0 are the same timeout. Six document edits that change
        # nothing are still six billable operations.
        _, before, after = tables(
            repo, [(CONFIG, "REQUEST_TIMEOUT_SECONDS = 30", "REQUEST_TIMEOUT_SECONDS = 30.0")]
        )
        assert diff_tables(before, after) == []

    def test_list_additions_and_removals(self, repo: Path):
        _, before, after = tables(
            repo,
            [
                (
                    API,
                    '    "POST /v1/circuits/{circuit_id}/provision": "provision_circuit",',
                    '    "POST /v1/circuits/{circuit_id}/activate": "activate_circuit",',
                )
            ],
        )
        change = diff_tables(before, after)[0]
        assert change.is_list
        assert change.added == ("POST /v1/circuits/{circuit_id}/activate",)
        assert change.removed == ("POST /v1/circuits/{circuit_id}/provision",)

    def test_reordering_a_list_is_not_a_change(self, repo: Path):
        registry = Registry.load(repo)
        before = read_facts(registry, WorkingTree(repo))
        path = repo / API
        lines = path.read_text().splitlines()
        route_lines = [i for i, ln in enumerate(lines) if ln.strip().startswith('"GET')]
        lines[route_lines[0]], lines[route_lines[1]] = lines[route_lines[1]], lines[route_lines[0]]
        path.write_text("\n".join(lines) + "\n")
        after = read_facts(registry, WorkingTree(repo))
        assert diff_tables(before, after) == []

    def test_an_unresolved_fact_is_never_a_change(self, repo: Path):
        # The new value is unknown, so any document edit would be a guess.
        _, before, after = tables(
            repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = compute()")]
        )
        assert diff_tables(before, after) == []
        assert "retry.max_attempts" in after.errors


class TestImpactSet:
    def test_only_documents_that_carry_the_fact_are_contacted(self, repo: Path):
        registry, before, after = tables(repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")])
        plan = build_plan(registry, before, after)
        assert [d.path for d in plan.documents] == [ADR, RUNBOOK]
        # The half of the claim that is about restraint.
        assert plan.untouched == [SLA, SPEC]

    def test_a_document_already_saying_the_new_value_costs_nothing(self, repo: Path):
        registry, before, after = tables(repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")])
        edit_file(repo, ADR, "attempted up to 3 times", "attempted up to 5 times")
        plan = build_plan(registry, before, after)
        assert ADR in plan.already_current
        assert plan.operations == 0 or all(d.path != ADR for d in plan.documents)

    def test_an_anchored_run_is_idempotent(self, repo: Path):
        # Applying the same drift twice must cost nothing the second time, or
        # a tool wired to a file-save hook would bill on every keystroke.
        registry, before, after = tables(repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")])
        edit_file(repo, ADR, "attempted up to 3 times", "attempted up to 5 times")
        plan = build_plan(registry, before, after)
        assert plan.operations == 0
        assert ADR in plan.already_current

    def test_prose_edits_are_not_idempotent_and_this_is_a_real_limitation(
        self, repo: Path
    ):
        # An honest test of a gap rather than a claim of a property. The prose
        # edit landed — "three attempts" now reads "five attempts" — but there
        # is no literal "5" to find, so the anchor check cannot tell an applied
        # prose edit from an unapplied one and will offer to send it again.
        # Documented in the README under limitations.
        registry, before, after = tables(repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")])
        edit_file(repo, RUNBOOK, "make three attempts", "make five attempts")
        plan = build_plan(registry, before, after, allow_prose=True)
        runbook = next(d for d in plan.documents if d.path == RUNBOOK)
        assert runbook.anchors["retry.max_attempts"].kind == ANCHOR_UNANCHORED
        assert "retry.max_attempts" in {c.key for c in runbook.to_send}

    def test_cost_drops_when_the_document_is_already_uploaded_unchanged(self, repo: Path):
        # Only the ADR is contacted: the runbook states the same fact in prose,
        # so it is held back rather than sent.
        registry, before, after = tables(repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")])
        plan = build_plan(registry, before, after)
        assert plan.operations == 2  # one upload + one edit

        uploaded = {ADR: content_hash((repo / ADR).read_text())}
        cheaper = build_plan(registry, before, after, uploaded=uploaded)
        assert cheaper.operations == 1

    def test_a_stale_upload_hash_forces_a_re_upload(self, repo: Path):
        registry, before, after = tables(repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")])
        plan = build_plan(registry, before, after, uploaded={ADR: "not-the-hash"})
        adr = next(d for d in plan.documents if d.path == ADR)
        assert adr.needs_upload


class TestAnchors:
    def test_a_literal_value_anchors(self, repo: Path):
        registry, before, after = tables(repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")])
        plan = build_plan(registry, before, after)
        adr = next(d for d in plan.documents if d.path == ADR)
        assert adr.anchors["retry.max_attempts"].kind == ANCHOR_LITERAL

    def test_a_value_stated_in_prose_is_held_back(self, repo: Path):
        registry, before, after = tables(repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")])
        plan = build_plan(registry, before, after)
        runbook = next(d for d in plan.documents if d.path == RUNBOOK)
        assert runbook.anchors["retry.max_attempts"].kind == ANCHOR_UNANCHORED
        assert "retry.max_attempts" not in {c.key for c in runbook.to_send}
        assert plan.unanchored_total == 1

    def test_allow_prose_sends_it_but_never_calls_it_verified(self, repo: Path):
        registry, before, after = tables(repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")])
        plan = build_plan(registry, before, after, allow_prose=True)
        runbook = next(d for d in plan.documents if d.path == RUNBOOK)
        assert "retry.max_attempts" in {c.key for c in runbook.to_send}
        assert "retry.max_attempts" not in {c.key for c in runbook.verifiable}

    def test_a_short_repeated_value_is_a_weak_anchor(self, repo: Path):
        # 1000 is both the default bandwidth and the rate limit. Quoting it is
        # an instruction to change a number the author never mentioned.
        registry, before, after = tables(
            repo, [(CONFIG, "DEFAULT_BANDWIDTH_MBPS = 1000", "DEFAULT_BANDWIDTH_MBPS = 10000")]
        )
        plan = build_plan(registry, before, after)
        spec = next(d for d in plan.documents if d.path == SPEC)
        assert spec.anchors["api.default_bandwidth_mbps"].kind == ANCHOR_WEAK

    def test_already_applied_is_detected_when_a_sibling_still_reads_the_old_value(
        self, repo: Path
    ):
        # The runbook states a retry backoff and a request timeout that both
        # read "30 seconds". After the backoff moves to 45, one "30 seconds"
        # remains and it belongs to the timeout. Reading that as "not yet
        # applied" made a live run re-send the same edit every round — it even
        # verified, because the new value really was present — and burn an
        # operation a round until the no-progress guard stopped it.
        registry, before, after = tables(
            repo, [(RETRY, "BACKOFF_SECONDS = 30", "BACKOFF_SECONDS = 45")]
        )
        edit_file(repo, RUNBOOK, "spaced 30 seconds apart", "spaced 45 seconds apart")
        plan = build_plan(registry, before, after)
        assert RUNBOOK in plan.already_current
        assert all(d.path != RUNBOOK for d in plan.documents)
        # The ADR carries the same fact and has not been updated, so it is
        # still contacted — the runbook simply costs nothing.
        assert [d.path for d in plan.documents] == [ADR]

    def test_a_genuinely_unapplied_change_is_not_mistaken_for_applied(self, repo: Path):
        # Guards the guard: with both sentences still reading "30 seconds",
        # two occurrences against one sibling is not "already done".
        registry, before, after = tables(
            repo, [(RETRY, "BACKOFF_SECONDS = 30", "BACKOFF_SECONDS = 45")]
        )
        plan = build_plan(registry, before, after)
        runbook = next(d for d in plan.documents if d.path == RUNBOOK)
        assert runbook.anchors["retry.backoff_seconds"].kind == ANCHOR_WEAK

    def test_current_is_detected_before_literal(self, repo: Path):
        registry, before, after = tables(repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")])
        edit_file(repo, ADR, "attempted up to 3 times", "attempted up to 5 times")
        plan = build_plan(registry, before, after)
        # Nothing to send, so nothing to upload either.
        assert all(d.path != ADR for d in plan.documents)


class TestInstructions:
    def test_quotes_the_old_and_new_values(self, repo: Path):
        registry, before, after = tables(repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")])
        plan = build_plan(registry, before, after)
        adr = next(d for d in plan.documents if d.path == ADR)
        # `literal` means exactly one occurrence, so the instruction says so
        # and never licenses a blanket substitution.
        assert 'as "3", once' in adr.instruction
        assert 'Replace that one occurrence with "5"' in adr.instruction
        assert "change all of them" not in adr.instruction
        assert "Do not reword anything else" in adr.instruction

    def test_two_facts_sharing_a_value_stop_quoting_it(self, repo: Path):
        # The Task 2 bug, carried over deliberately: telling a model to replace
        # one string with two different values is a contradiction, and it
        # resolved it differently in two documents that had to agree.
        registry, before, after = tables(
            repo,
            [
                (RETRY, "BACKOFF_SECONDS = 30", "BACKOFF_SECONDS = 45"),
                (CONFIG, "REQUEST_TIMEOUT_SECONDS = 30", "REQUEST_TIMEOUT_SECONDS = 20"),
            ],
        )
        plan = build_plan(registry, before, after)
        runbook = next(d for d in plan.documents if d.path == RUNBOOK)
        instruction = runbook.instruction
        # One item per instruction now, so only the first change is in this
        # round — but the ambiguity is still named, and the value is never
        # quoted as a blanket find-and-replace target.
        assert "as \"30 seconds\", once" not in instruction
        assert "and only that one" in instruction
        assert "API request timeout" in instruction
        assert 'Leave every other occurrence of "30 seconds" exactly as it is' in instruction
        assert 'set the value to "45 seconds"' in instruction

    def test_an_anchor_that_is_another_facts_value_stops_being_quoted(self, repo: Path):
        # The worst bug this build has produced, reproduced as a test.
        #
        # The runbook carries the retry backoff (30 seconds) and the carrier
        # request timeout (also 30 seconds). Only the backoff changes. The old
        # rule compared changed facts against each other, saw one change, and
        # emitted "wherever this document says 30 seconds ... change all of
        # them". A live run did exactly that, to both sentences, and the
        # runbook then told on-call the call timeout was 45 seconds while the
        # code said 30. Verification passed, because 45 seconds was present.
        registry, before, after = tables(repo, [(RETRY, "BACKOFF_SECONDS = 30", "BACKOFF_SECONDS = 45")])
        plan = build_plan(registry, before, after)
        runbook = next(d for d in plan.documents if d.path == RUNBOOK)

        anchor = runbook.anchors["retry.backoff_seconds"]
        assert anchor.kind == ANCHOR_WEAK
        assert "API request timeout" in anchor.note
        assert "change all of them" not in runbook.instruction
        assert "and only that one" in runbook.instruction

    def test_a_repeated_anchor_is_weak_even_with_no_sibling_fact(self, repo: Path):
        # Two occurrences of the same value with no second fact to blame. There
        # is still no way to know from outside that both mean the same thing,
        # so it still gets the careful phrasing.
        edit_file(repo, ADR, "spaced 30 seconds apart", "spaced 30 seconds apart (30 seconds)")
        registry, before, after = tables(repo, [(RETRY, "BACKOFF_SECONDS = 30", "BACKOFF_SECONDS = 45")])
        plan = build_plan(registry, before, after)
        adr = next(d for d in plan.documents if d.path == ADR)
        assert adr.anchors["retry.backoff_seconds"].kind == ANCHOR_WEAK

    def test_unchanged_covered_facts_become_invariants(self, repo: Path):
        registry, before, after = tables(repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")])
        plan = build_plan(registry, before, after)
        adr = next(d for d in plan.documents if d.path == ADR)
        assert {i["key"] for i in adr.invariants} == {
            "retry.backoff_seconds",
            "queue.dead_letter_topic",
        }
        assert "retry.max_attempts" not in {i["key"] for i in adr.invariants}

    def test_a_fact_stated_only_in_prose_is_not_an_invariant(self, repo: Path):
        # There is nothing to check for, so promising to check it would be a lie.
        registry, before, after = tables(
            repo, [(CONFIG, "REQUEST_TIMEOUT_SECONDS = 30", "REQUEST_TIMEOUT_SECONDS = 20")]
        )
        plan = build_plan(registry, before, after)
        runbook = next(d for d in plan.documents if d.path == RUNBOOK)
        assert "retry.max_attempts" not in {i["key"] for i in runbook.invariants}

    def test_acronyms_survive_the_sentence_case(self, repo: Path):
        registry, before, after = tables(
            repo, [(CONFIG, "REQUEST_TIMEOUT_SECONDS = 30", "REQUEST_TIMEOUT_SECONDS = 20")]
        )
        plan = build_plan(registry, before, after)
        spec = next(d for d in plan.documents if d.path == SPEC)
        assert "the API request timeout" in spec.instruction
        assert "api request timeout" not in spec.instruction

    def test_a_list_change_names_each_addition_and_removal(self, repo: Path):
        registry, before, after = tables(
            repo,
            [
                (
                    API,
                    '    "POST /v1/circuits/{circuit_id}/provision": "provision_circuit",',
                    '    "POST /v1/circuits/{circuit_id}/activate": "activate_circuit",',
                )
            ],
        )
        plan = build_plan(registry, before, after)
        spec = next(d for d in plan.documents if d.path == SPEC)
        assert 'Add an entry for each of: "POST /v1/circuits/{circuit_id}/activate"' in spec.instruction
        assert 'Remove the entry for each of: "POST /v1/circuits/{circuit_id}/provision"' in spec.instruction

    def test_prose_instruction_asks_for_the_spelled_out_form(self, repo: Path):
        registry, before, after = tables(repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 5")])
        plan = build_plan(registry, before, after, allow_prose=True)
        runbook = next(d for d in plan.documents if d.path == RUNBOOK)
        assert "in prose rather" in runbook.instruction
        assert "spelled-out form" in runbook.instruction


class TestBlocking:
    def test_an_unreadable_fact_blocks_the_whole_run(self, repo: Path):
        registry, before, after = tables(
            repo, [(RETRY, "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = compute()")]
        )
        plan = build_plan(registry, before, after)
        assert plan.blocked
        assert "retry.max_attempts" in plan.unresolved


class TestAudit:
    def test_reports_prose_and_weak_anchors(self, repo: Path):
        registry = Registry.load(repo)
        findings = audit(registry, read_facts(registry, WorkingTree(repo)))
        by = {(f.path, f.key): f for f in findings}
        assert by[(RUNBOOK, "retry.max_attempts")].status == AUDIT_PROSE
        assert by[(SPEC, "api.default_bandwidth_mbps")].status == AUDIT_WEAK
        assert by[(ADR, "retry.max_attempts")].count == 1

    def test_a_coverage_claim_that_would_do_nothing_is_visible_before_it_matters(
        self, repo: Path
    ):
        edit_file(repo, SLA, "contracted at 99.95% availability", "contracted at four nines")
        registry = Registry.load(repo)
        findings = audit(registry, read_facts(registry, WorkingTree(repo)))
        finding = next(f for f in findings if (f.path, f.key) == (SLA, "sla.uptime_target"))
        assert finding.status == AUDIT_PROSE
