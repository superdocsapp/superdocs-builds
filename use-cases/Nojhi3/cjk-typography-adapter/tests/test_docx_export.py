import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Mm, Pt
from pathlib import Path

from adapter.profile import load_profile
from adapter.pipeline import adapt

JA = load_profile("ja")
SAMPLE = Path(__file__).parent.parent / "data" / "sample" / "sample.html"


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("docx")
    adapt(SAMPLE, locale="ja", out_dir=out)
    return out


def test_page_geometry(out_dir):
    doc = Document(out_dir / "adapted.docx")
    section = doc.sections[0]
    assert section.page_width.twips == Mm(210).twips
    assert section.page_height.twips == Mm(297).twips
    assert section.top_margin.twips == Mm(25).twips
    assert section.bottom_margin.twips == Mm(25).twips
    assert section.left_margin.twips == Mm(20).twips
    assert section.right_margin.twips == Mm(20).twips


def test_normal_style_typography(out_dir):
    doc = Document(out_dir / "adapted.docx")
    normal = doc.styles["Normal"]
    assert normal.font.size == Pt(10.5)
    assert normal.font.name == "Times New Roman"
    rfonts = normal.element.get_or_add_rPr().get_or_add_rFonts()
    assert rfonts.get(qn("w:eastAsia")) == "Yu Mincho"
    assert normal.paragraph_format.line_spacing == 1.5
    assert normal.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY


def test_language_set(out_dir):
    doc = Document(out_dir / "adapted.docx")
    xml = doc.styles["Normal"].element.get_or_add_rPr().xml
    assert 'w:eastAsia="ja"' in xml or "ja-JP" in xml or 'w:eastAsia="ja-JP"' in xml


def test_kinsoku_compat_set(out_dir):
    doc = Document(out_dir / "adapted.docx")
    xml = doc.settings.element.xml
    assert "kinsoku" in xml


def test_heading_style(out_dir):
    doc = Document(out_dir / "adapted.docx")
    h1 = doc.styles["Heading 1"]
    assert h1.font.size == Pt(16)
    assert h1.font.bold is False


def test_body_text_adapted(out_dir):
    doc = Document(out_dir / "adapted.docx")
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Budget review on Tuesday。" in text or "delivered by Friday of the last month。" in text
    assert "（subject to annual renewal）。" in text
    assert "「the Provider」" in text
    assert "備考（別紙参照）。" in text


def test_table_present_with_cells(out_dir):
    doc = Document(out_dir / "adapted.docx")
    assert len(doc.tables) == 1
    table = doc.tables[0]
    assert table.rows[0].cells[0].text == "Plan"
    assert table.rows[2].cells[1].text == "$29"
    assert table.rows[2].cells[2].text == "10 GB"


def test_list_items(out_dir):
    doc = Document(out_dir / "adapted.docx")
    texts = [p.text for p in doc.paragraphs]
    assert any("Uptime target: 99.9%, measured quarterly。" in t for t in texts)
    assert any("critical issues （P1）。" in t for t in texts)
