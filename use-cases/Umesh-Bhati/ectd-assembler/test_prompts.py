import unittest

from main import build_section_prompt, build_toc_prompt


class TestPrompts(unittest.TestCase):
    def test_section_prompt_tells_ai_not_to_duplicate_heading(self):
        prompt = build_section_prompt("2.5.2", "Clinical Efficacy", ["study_report_2.txt"])

        self.assertIn("already contains a Heading 1 titled '2.5.2 Clinical Efficacy'", prompt)
        self.assertIn("Do NOT add a new heading", prompt)
        self.assertIn("Replace ONLY the placeholder", prompt)

    def test_toc_prompt_lists_sections(self):
        prompt = build_toc_prompt(["2.5.1 Clinical Pharmacology", "2.5.2 Clinical Efficacy"])

        self.assertIn("2.5.1 Clinical Pharmacology", prompt)
        self.assertIn("2.5.2 Clinical Efficacy", prompt)
        self.assertIn("Do not change any section body text", prompt)


if __name__ == "__main__":
    unittest.main()
