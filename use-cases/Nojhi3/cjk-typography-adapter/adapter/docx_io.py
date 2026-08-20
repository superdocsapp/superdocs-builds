from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from .htmltree import Node, collect_plain_text

LINK_BLUE = RGBColor(0x05, 0x63, 0xC1)
HEADING_SIZE = {"h1": 16, "h2": 14, "h3": 12, "h4": 11, "h5": 11, "h6": 11}


def _set_east_asia(style_or_run, font: str) -> None:
    rpr = style_or_run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:eastAsia"), font)


def _configure_styles(doc: Document, profile) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = profile.latin_primary
    normal.font.size = Pt(profile.body_size_pt)
    _set_east_asia(normal, profile.cjk_body_font)
    pf = normal.paragraph_format
    pf.line_spacing = profile.line_spacing
    pf.space_after = Pt(profile.paragraph_spacing_pt)
    pf.alignment = getattr(WD_ALIGN_PARAGRAPH, profile.text_align.upper())
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), "en-US")
    lang.set(qn("w:eastAsia"), profile.lang)
    normal.element.get_or_add_rPr().append(lang)
    for level, size in profile.heading_sizes_pt.items():
        style = doc.styles[f"Heading {level[1]}"]
        style.font.size = Pt(size)
        style.font.name = profile.latin_primary
        style.font.bold = profile.heading_bold
        style.font.color.rgb = RGBColor(0, 0, 0)
        _set_east_asia(style, profile.cjk_body_font)
    settings = doc.settings.element
    compat = OxmlElement("w:compat")
    kinsoku = OxmlElement("w:kinsoku")
    kinsoku.set(qn("w:val"), "1")
    compat.append(kinsoku)
    settings.append(compat)


def _set_run(run, profile, bold: bool = False, italic: bool = False, size_pt=None) -> None:
    run.font.name = profile.latin_primary
    run.font.size = Pt(size_pt or profile.body_size_pt)
    run.font.bold = bold
    run.font.italic = italic
    _set_east_asia(run, profile.cjk_body_font)


def _add_text_runs(paragraph, node: Node, profile, bold: bool = False, italic: bool = False) -> None:
    for child in node.children:
        if isinstance(child, str):
            run = paragraph.add_run(child)
            _set_run(run, profile, bold=bold, italic=italic)
        elif child.tag == "strong":
            _add_text_runs(paragraph, child, profile, bold=True, italic=italic)
        elif child.tag == "em":
            _add_text_runs(paragraph, child, profile, bold=bold, italic=True)
        elif child.tag == "code":
            run = paragraph.add_run(collect_plain_text(child))
            _set_run(run, profile, bold=bold)
            run.font.name = "Consolas"
        elif child.tag == "a":
            run = paragraph.add_run(collect_plain_text(child))
            _set_run(run, profile, bold=bold)
            run.font.color.rgb = LINK_BLUE
            run.font.underline = True
        elif child.tag == "br":
            paragraph.add_run().add_break()
        else:
            _add_text_runs(paragraph, child, profile, bold=bold, italic=italic)


def _add_bottom_border(paragraph) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "8")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "333333")
    pbdr.append(bottom)
    ppr.append(pbdr)


def _walk_blocks(doc: Document, node: Node, profile) -> None:
    for child in node.children:
        if not isinstance(child, Node):
            continue
        tag = child.tag
        if tag == "p":
            paragraph = doc.add_paragraph()
            _add_text_runs(paragraph, child, profile)
        elif tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
            level = int(tag[1])
            paragraph = doc.add_paragraph(style=f"Heading {level}")
            _add_text_runs(paragraph, child, profile, bold=profile.heading_bold)
        elif tag == "ul":
            _walk_list(doc, child, profile, ordered=False)
        elif tag == "ol":
            _walk_list(doc, child, profile, ordered=True)
        elif tag == "blockquote":
            paragraph = doc.add_paragraph()
            paragraph.paragraph_format.left_indent = Pt(24)
            _add_text_runs(paragraph, child, profile)
        elif tag == "hr":
            paragraph = doc.add_paragraph()
            _add_bottom_border(paragraph)
        elif tag == "table":
            _walk_table(doc, child, profile)
        elif tag in ("div", "section", "article", "main", "body", "html", "head", "style", "script"):
            _walk_blocks(doc, child, profile)
        elif tag == "pre":
            paragraph = doc.add_paragraph()
            run = paragraph.add_run(collect_plain_text(child))
            _set_run(run, profile)
            run.font.name = "Consolas"


def _walk_list(doc: Document, node: Node, profile, ordered: bool) -> None:
    style_name = "List Number" if ordered else "List Bullet"
    for child in node.children:
        if isinstance(child, Node) and child.tag == "li":
            paragraph = doc.add_paragraph(style=style_name)
            _add_text_runs(paragraph, child, profile)
        elif isinstance(child, Node) and child.tag in ("ul", "ol"):
            _walk_list(doc, child, profile, ordered=(child.tag == "ol"))


def _walk_table(doc: Document, node: Node, profile) -> None:
    rows = []
    for tr in node.children:
        if isinstance(tr, Node) and tr.tag == "tr":
            cells = []
            for cell in tr.children:
                if isinstance(cell, Node) and cell.tag in ("td", "th"):
                    cells.append(collect_plain_text(cell))
            rows.append(cells)
    if not rows:
        return
    ncols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=ncols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for ri, row in enumerate(rows):
        for ci, cell_text in enumerate(row):
            cell = table.cell(ri, ci)
            cell.paragraphs[0].text = ""
            run = cell.paragraphs[0].add_run(cell_text)
            _set_run(run, profile, bold=(ri == 0))


def render_docx(tree: Node, profile, out_path) -> None:
    doc = Document()
    section = doc.sections[0]
    p = profile.page
    section.page_width = Mm(p["width_mm"])
    section.page_height = Mm(p["height_mm"])
    section.top_margin = Mm(p["margin_top_mm"])
    section.bottom_margin = Mm(p["margin_bottom_mm"])
    section.left_margin = Mm(p["margin_left_mm"])
    section.right_margin = Mm(p["margin_right_mm"])
    _configure_styles(doc, profile)
    _walk_blocks(doc, tree, profile)
    doc.save(out_path)
