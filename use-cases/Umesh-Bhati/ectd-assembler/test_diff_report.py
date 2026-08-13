import os
import tempfile
import unittest

from docx import Document

from diff_report import compare_section_exports, extract_section_texts


class TestDiffReport(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

    def _write_doc(self, filename: str, section_contents: dict[str, str]) -> str:
        path = os.path.join(self.tempdir, filename)
        doc = Document()
        for section_id, body in section_contents.items():
            doc.add_heading(f"{section_id} Section", level=1)
            doc.add_paragraph(body)
        doc.save(path)
        return path

    def test_extract_section_texts(self):
        path = self._write_doc(
            "sample.docx",
            {"2.5.1": "PK facts", "2.5.2": "Efficacy facts"},
        )
        texts = extract_section_texts(path, ["2.5.1", "2.5.2"])
        self.assertIn("PK facts", texts["2.5.1"])
        self.assertIn("Efficacy facts", texts["2.5.2"])

    def test_compare_section_exports_passes_when_only_expected_sections_change(self):
        previous = self._write_doc(
            "previous.docx",
            {"2.5.1": "unchanged A", "2.5.2": "old B", "2.5.3": "old C"},
        )
        current = self._write_doc(
            "current.docx",
            {"2.5.1": "unchanged A", "2.5.2": "new B", "2.5.3": "new C"},
        )

        report = compare_section_exports(
            previous,
            current,
            ["2.5.1", "2.5.2", "2.5.3"],
            expected_changed=["2.5.2", "2.5.3"],
        )

        self.assertTrue(report.proof_passed)
        self.assertEqual(report.unchanged_sections, ["2.5.1"])
        self.assertEqual(report.changed_sections, ["2.5.2", "2.5.3"])


if __name__ == "__main__":
    unittest.main()
