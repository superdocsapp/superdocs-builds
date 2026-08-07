"""
Stdlib-only regression tests for the disclosure scanner in bgcheck_generator.py.

Covers the real bug found during live testing: the first version of
cmd_verify's regex flagged the disclosure template's own self-description
sentence ("No release, waiver, authorization ... is contained in this
document") as a violation, because it matched the words without noticing
they were negated. Fixed with sentence-scoped, negation-aware scanning.
These tests pin both directions: the negated sentence must PASS, and a
real (non-negated) injected clause must still FAIL.

Run: python -m unittest tests/test_verify_stdlib.py -v
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bgcheck_generator as gen  # noqa: E402


def scan(html: str):
    """Runs the same sentence-scoped, negation-aware scan cmd_verify uses,
    against arbitrary HTML, without touching the filesystem."""
    plain = gen._strip_tags(html)
    violations = []
    for sentence in gen._split_sentences(plain):
        for pattern in gen.FORBIDDEN_IN_DISCLOSURE:
            for m in re.finditer(pattern, sentence, re.IGNORECASE):
                preceding = sentence[: m.start()]
                if gen.NEGATION_CUES.search(preceding):
                    continue
                violations.append((pattern, m.group(0)))
    return violations


class TestNegationAwareScan(unittest.TestCase):
    def test_real_disclosure_self_description_sentence_passes(self):
        # The actual sentence from data/disclosure_template.html, live-generated
        # through SuperDocs and originally (wrongly) flagged as a violation.
        html = (
            "<p>This document is a disclosure only. No release, waiver, "
            "authorization, or other acknowledgment is contained in or "
            "attached to this document.</p>"
        )
        self.assertEqual(scan(html), [])

    def test_real_waiver_clause_still_caught(self):
        # A genuine smuggled-in clause, not negated — must still fail.
        html = "<p>By signing below you waive any right to dispute this report.</p>"
        violations = scan(html)
        self.assertTrue(violations, "a real waiver clause must still be caught")

    def test_real_liability_release_clause_still_caught(self):
        html = (
            "<p>Candidate releases the company from all liability arising "
            "from this background check.</p>"
        )
        violations = scan(html)
        patterns_matched = {p for p, _ in violations}
        self.assertTrue(
            any("releas" in p for p in patterns_matched),
            "a real release clause must still be caught",
        )
        self.assertTrue(
            any("liabilit" in p for p in patterns_matched),
            "a real liability clause must still be caught",
        )

    def test_i_authorize_language_caught_outside_negation(self):
        html = "<p>I authorize the company to run this report.</p>"
        violations = scan(html)
        self.assertTrue(violations)

    def test_end_to_end_verify_passes_on_actual_generated_output(self):
        """Full cmd_verify() against the real, live SuperDocs-generated
        output/disclosure.html — proves the fix holds on the actual
        artifact being submitted, not just a synthetic snippet."""
        out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
        disclosure_path = os.path.join(out_dir, "disclosure.html")
        if not os.path.exists(disclosure_path):
            self.skipTest("output/disclosure.html not generated yet — run `generate` first")
        old_output_dir = gen.OUTPUT_DIR
        gen.OUTPUT_DIR = out_dir
        try:
            self.assertTrue(gen.cmd_verify())
        finally:
            gen.OUTPUT_DIR = old_output_dir

    def test_merge_fields_replaces_all_placeholders(self):
        template = "<p>{{candidate_name}} applied for {{position_title}}.</p>"
        merged = gen.merge_fields(
            template, {"candidate_name": "Jordan T. Ellis", "position_title": "Supervisor"}
        )
        self.assertNotIn("{{", merged)
        self.assertIn("Jordan T. Ellis", merged)
        self.assertIn("Supervisor", merged)


if __name__ == "__main__":
    unittest.main()
