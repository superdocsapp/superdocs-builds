import os
import tempfile
import unittest
import zipfile

from docx import Document
from docx.oxml.ns import qn

from docx_transform import convert_citations_to_footnotes, make_live_toc, postprocess_export


def _make_sample_doc(path: str) -> None:
    doc = Document()
    doc.add_heading("Module 2: Clinical Summary", 0)
    doc.add_heading("Table of Contents", level=1)
    doc.add_paragraph("[Table of contents will be generated.]")
    doc.add_heading("2.5.1 Clinical Pharmacology", level=1)
    p = doc.add_paragraph(
        "In healthy volunteers the half-life was 4.5 hours "
        "[Study Report 1, Section 1.1]. Cmax was reached at 2 hours "
        "[Study Report 1, Section 1.2]."
    )
    doc.add_heading("2.5.2 Clinical Efficacy", level=1)
    doc.add_paragraph("Response was 75% versus 30% placebo [Study Report 2, Section 2.1].")
    doc.save(path)


class TestConvertCitations(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

    def test_converts_bracketed_citations_to_footnotes(self):
        src = os.path.join(self.tempdir, "in.docx")
        _make_sample_doc(src)
        doc = Document(src)

        count = convert_citations_to_footnotes(doc)
        self.assertEqual(count, 3)

        out = os.path.join(self.tempdir, "out.docx")
        doc.save(out)

        with zipfile.ZipFile(out) as z:
            self.assertIn("word/footnotes.xml", z.namelist())
            footnotes = z.read("word/footnotes.xml").decode("utf-8")
            self.assertIn("Study Report 1, Section 1.1", footnotes)
            self.assertIn("Study Report 1, Section 1.2", footnotes)
            self.assertIn("Study Report 2, Section 2.1", footnotes)

            document_xml = z.read("word/document.xml").decode("utf-8")
            self.assertIn("w:footnoteReference", document_xml)
            self.assertNotIn("Study Report 1, Section 1.1", document_xml)

        reopened = Document(out)
        para_text = "\n".join(p.text for p in reopened.paragraphs)
        self.assertNotIn("[Study Report 1", para_text)
        self.assertIn("In healthy volunteers the half-life was 4.5 hours", para_text)

    def test_no_citations_leaves_document_untouched(self):
        src = os.path.join(self.tempdir, "in.docx")
        doc = Document()
        doc.add_paragraph("Plain paragraph with no citations.")
        doc.save(src)

        doc = Document(src)
        count = convert_citations_to_footnotes(doc)
        self.assertEqual(count, 0)

        out = os.path.join(self.tempdir, "out.docx")
        doc.save(out)
        with zipfile.ZipFile(out) as z:
            self.assertNotIn("word/footnotes.xml", z.namelist())

    def test_postprocess_export_report(self):
        src = os.path.join(self.tempdir, "in.docx")
        dst = os.path.join(self.tempdir, "out.docx")
        _make_sample_doc(src)
        report = postprocess_export(src, dst)
        self.assertEqual(report["footnotes_created"], 3)
        self.assertTrue(report["live_toc_inserted"])


class TestLiveToc(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

    def test_toc_bullets_replaced_by_field(self):
        src = os.path.join(self.tempdir, "in.docx")
        _make_sample_doc(src)
        doc = Document(src)

        self.assertTrue(make_live_toc(doc))

        out = os.path.join(self.tempdir, "out.docx")
        doc.save(out)

        with zipfile.ZipFile(out) as z:
            document_xml = z.read("word/document.xml").decode("utf-8")
            self.assertIn("TOC \\o", document_xml)
            self.assertIn("w:fldChar w:fldCharType=\"begin\"", document_xml)
            self.assertIn('w:dirty="true"', document_xml)
            self.assertNotIn("[Table of contents will be generated.]", document_xml)

    def test_missing_toc_heading_is_noop(self):
        src = os.path.join(self.tempdir, "in.docx")
        doc = Document()
        doc.add_heading("2.5.1 Clinical Pharmacology", level=1)
        doc.add_paragraph("Body text.")
        doc.save(src)

        doc = Document(src)
        self.assertFalse(make_live_toc(doc))


if __name__ == "__main__":
    unittest.main()
