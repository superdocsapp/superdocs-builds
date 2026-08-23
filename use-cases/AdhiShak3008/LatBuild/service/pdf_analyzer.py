"""
pdf_analyzer.py
PDF layout analysis — extracts text blocks in correct reading order.

Architecture guarantee:
  For every page:
    1. Extract all words with bounding boxes.
    2. Detect the column split boundary (a single x value).
    3. Assign each word to a column by comparing its x-midpoint to the split.
    4. Sort each column's words by top (y-coordinate) independently.
    5. Group into lines within each column.
    6. Group lines into paragraphs within each column.
    7. Emit blocks: all of col-0 first, then all of col-1.

  Words from different columns NEVER mix. The split boundary is the
  enforced gate — nothing crosses it during extraction.

Column detection strategy:
  - Ignore wide words (title, author lines spanning both columns).
  - Build a histogram of word x-midpoints in 10pt buckets.
  - Find the lowest-density bucket between 30% and 70% of page width.
  - That bucket is the split boundary.
  - If no meaningful valley exists, treat the page as single-column.

Paragraph grouping strategy:
  - Measure all inter-line gaps within a column.
  - Use median gap × 2.5 as the paragraph-break threshold (adaptive).
  - This handles PDFs where body-text line spacing is ~1pt and
    paragraph/heading gaps are 5-15pt.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple
import pdfplumber


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class BBox:
    x0: float
    y0: float   # top (PDF top-left origin)
    x1: float
    y1: float   # bottom

    @property
    def width(self):
        return self.x1 - self.x0

    @property
    def height(self):
        return abs(self.y1 - self.y0)

    @property
    def area(self):
        return self.width * self.height

    def as_tuple(self):
        return (self.x0, self.y0, self.x1, self.y1)

    def overlaps(self, other: "BBox") -> bool:
        sy0, sy1 = min(self.y0, self.y1), max(self.y0, self.y1)
        oy0, oy1 = min(other.y0, other.y1), max(other.y0, other.y1)
        return not (
            self.x1 <= other.x0 or other.x1 <= self.x0 or
            sy1 <= oy0 or oy1 <= sy0
        )


@dataclass
class TextBlock:
    text: str
    bbox: BBox
    page: int           # 1-indexed
    column: int         # 0-indexed column within page
    fontname: str
    fontsize: float
    is_bold: bool
    is_heading: bool
    reading_order: int  # global, monotone across entire document
    line_height: float = 0.0
    paragraph_spacing: float = 0.0


@dataclass
class NonContentElement:
    type: str           # "image" | "table"
    page: int
    bbox: BBox
    anchor: str = "absolute"


@dataclass
class ColumnRegion:
    index: int
    x0: float
    x1: float
    width: float

    @property
    def mid(self):
        return (self.x0 + self.x1) / 2


@dataclass
class PageLayout:
    page_number: int
    width: float
    height: float
    columns: List[ColumnRegion]
    split_x: float              # the actual split boundary used for word assignment
    text_blocks: List[TextBlock]
    non_content: List[NonContentElement]
    margin_top: float
    margin_bottom: float
    margin_left: float
    margin_right: float


@dataclass
class DocumentGrammar:
    page_width: float
    page_height: float
    margin_top: float
    margin_bottom: float
    margin_left: float
    margin_right: float
    column_count: int
    column_regions: List[ColumnRegion]
    split_x: float              # primary column split (0 if single-column)
    column_gap: float
    body_fontname: str
    body_fontsize: float
    body_line_height: float
    paragraph_spacing: float
    heading_styles: Dict[str, dict]


@dataclass
class AnalyzedDocument:
    path: str
    page_count: int
    grammar: DocumentGrammar
    pages: List[PageLayout]
    all_blocks: List[TextBlock]
    non_content: List[NonContentElement]


# ---------------------------------------------------------------------------
# Heading vocabulary
# ---------------------------------------------------------------------------

KNOWN_HEADINGS = {
    "abstract", "introduction", "conclusion", "conclusions",
    "references", "acknowledgment", "acknowledgments",
    "acknowledgement", "acknowledgements",
    "related work", "background", "motivation", "overview",
    "discussion", "future work", "appendix",
    "keywords", "index terms", "keyword", "key words",
    "methodology", "methods", "results", "experiments",
    "evaluation", "implementation", "system", "architecture",
    "design", "analysis", "contributions", "contribution",
    "limitations", "summary",
}

# Roman numerals up to XX
_ROMAN = r'(?:X{0,2}(?:IX|IV|V?I{0,3}))'
# IEEE section heading: "I.", "II.", "III.", ... followed by text
_ROMAN_HEADING_RE = re.compile(r'^' + _ROMAN + r'\.\s+\S', re.IGNORECASE)
# IEEE subsection: "A.", "B.", ... followed by text
_ALPHA_HEADING_RE = re.compile(r'^[A-Z]\.\s+\S')
# Keywords line
_KEYWORD_RE = re.compile(
    r'^(index\s+terms|keywords?|key\s+words)\s*[\u2014:—]',
    re.IGNORECASE
)
# Numbered / Task headings: "TASK 1. ...", "1. ...", "2.1 ..."
_TASK_NUMBER_RE = re.compile(
    r'^(?:TASK\s+\d+|SECTION\s+\d+|\d+\.\d+|\d+\.)\s+[A-Z]',
    re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class PDFAnalyzer:

    def analyze(self, pdf_path: str) -> AnalyzedDocument:
        pages = []
        all_blocks: List[TextBlock] = []
        all_non_content: List[NonContentElement] = []
        ro = [0]   # reading order counter

        with pdfplumber.open(pdf_path) as pdf:
            grammar = self._extract_grammar(pdf)

            for page_obj in pdf.pages:
                pn = page_obj.page_number   # 1-indexed
                pw, ph = float(page_obj.width), float(page_obj.height)

                non_content = self._extract_non_content(page_obj, pn)
                blocks, split_x, cols = self._extract_text_blocks(
                    page_obj, pn, ph, grammar, ro, non_content
                )

                layout = PageLayout(
                    page_number=pn,
                    width=pw, height=ph,
                    columns=cols,
                    split_x=split_x,
                    text_blocks=blocks,
                    non_content=non_content,
                    margin_top=grammar.margin_top,
                    margin_bottom=grammar.margin_bottom,
                    margin_left=grammar.margin_left,
                    margin_right=grammar.margin_right,
                )
                pages.append(layout)
                all_blocks.extend(blocks)
                all_non_content.extend(non_content)

        # Post-process: replace block text with pymupdf's cleaner extraction.
        # pymupdf infers spaces from glyph gaps, solving the concatenation problem.
        self._replace_text_with_pymupdf(pdf_path, all_blocks)

        return AnalyzedDocument(
            path=pdf_path,
            page_count=len(pages),
            grammar=grammar,
            pages=pages,
            all_blocks=all_blocks,
            non_content=all_non_content,
        )

    # ------------------------------------------------------------------
    # Grammar
    # ------------------------------------------------------------------

    def _extract_grammar(self, pdf) -> DocumentGrammar:
        font_sizes: Dict[float, int] = {}
        all_words = []

        for page_obj in pdf.pages[:min(4, len(pdf.pages))]:
            words = page_obj.extract_words(
                extra_attrs=["fontname", "size"], use_text_flow=False
            )
            for w in words:
                sz = round(float(w.get("size", 10)), 1)
                font_sizes[sz] = font_sizes.get(sz, 0) + 1
            all_words.extend(words)

        body_fontsize = max(font_sizes, key=font_sizes.get) if font_sizes else 10.0

        fn_counts: Dict[str, int] = {}
        for w in all_words:
            if round(float(w.get("size", 10)), 1) == body_fontsize:
                fn = w.get("fontname", "")
                fn_counts[fn] = fn_counts.get(fn, 0) + 1
        body_fontname = max(fn_counts, key=fn_counts.get) if fn_counts else "Times-Roman"

        # Line height from inter-line gaps (per column)
        pw = float(pdf.pages[0].width)
        ph = float(pdf.pages[0].height)

        # Prefer a clean body page (page 2) to establish column geometry without page 1 title banners
        rep_page = pdf.pages[1] if len(pdf.pages) > 1 else pdf.pages[0]
        rep_words = rep_page.extract_words(
            extra_attrs=["fontname", "size"], use_text_flow=False
        )
        split_x, cols, is_two_col = self._find_split(rep_words, pw, ph)
        if not is_two_col and len(pdf.pages) > 1:
            first_words = pdf.pages[0].extract_words(
                extra_attrs=["fontname", "size"], use_text_flow=False
            )
            split_x, cols, _ = self._find_split(first_words, pw, ph)

        line_height = body_fontsize * 1.2
        all_gaps = []
        for page_obj in pdf.pages[:3]:
            words = page_obj.extract_words(
                extra_attrs=["fontname", "size"], use_text_flow=False
            )
            sx, _, _ = self._find_split(words, float(page_obj.width), float(page_obj.height))
            for col_words in self._split_words_by_column(words, sx,
                                                          float(page_obj.width),
                                                          float(page_obj.height)):
                lines = self._group_words_into_lines(col_words)
                for i in range(1, len(lines)):
                    pb = max(w["bottom"] for w in lines[i - 1])
                    ct = min(w["top"]    for w in lines[i])
                    g  = ct - pb
                    if 0 < g < body_fontsize * 4:
                        all_gaps.append(g)

        if all_gaps:
            all_gaps.sort()
            line_height = body_fontsize + all_gaps[len(all_gaps) // 2]

        # Margins
        all_tops, all_bots = [], []
        for page_obj in pdf.pages[:2]:
            ws = page_obj.extract_words()
            if ws:
                all_tops.append(min(w["top"]    for w in ws))
                all_bots.append(max(w["bottom"] for w in ws))
        margin_top    = min(all_tops) if all_tops else ph * 0.1
        margin_bottom = ph - max(all_bots) if all_bots else ph * 0.1
        margin_left   = cols[0].x0 if cols else pw * 0.08
        margin_right  = pw - cols[-1].x1 if cols else pw * 0.08

        # Heading styles
        heading_styles: Dict[str, dict] = {}
        for page_obj in pdf.pages[:4]:
            for w in page_obj.extract_words(extra_attrs=["fontname", "size"],
                                            use_text_flow=False):
                sz = round(float(w.get("size", 10)), 1)
                fn = w.get("fontname", "")
                if sz > body_fontsize + 1:
                    lvl = "h1" if sz > body_fontsize + 3 else "h2"
                    if lvl not in heading_styles:
                        heading_styles[lvl] = {
                            "fontname": fn, "fontsize": sz,
                            "is_bold": "bold" in fn.lower() or "Bold" in fn,
                        }

        return DocumentGrammar(
            page_width=pw, page_height=ph,
            margin_top=margin_top, margin_bottom=margin_bottom,
            margin_left=margin_left, margin_right=margin_right,
            column_count=len(cols),
            column_regions=cols,
            split_x=split_x,
            column_gap=max(0.0, cols[1].x0 - cols[0].x1) if len(cols) > 1 else 0.0,
            body_fontname=body_fontname,
            body_fontsize=body_fontsize,
            body_line_height=line_height,
            paragraph_spacing=line_height * 0.8,
            heading_styles=heading_styles,
        )

    # ------------------------------------------------------------------
    # Column detection — returns (split_x, columns, is_two_col)
    # ------------------------------------------------------------------

    def _find_split(
        self, words: list, page_width: float, page_height: float
    ) -> Tuple[float, List[ColumnRegion], bool]:
        """
        Find the column split boundary using x-midpoint valley detection.

        Returns:
            split_x   — the x-coordinate used to divide left/right columns.
                        0.0 if single-column.
            columns   — list of ColumnRegion (1 or 2 elements)
            two_col   — True if two-column layout detected
        """
        # Filter to content zone only
        cw = [w for w in words
              if page_height * 0.05 < w["top"] < page_height * 0.95]
        if not cw:
            return 0.0, [ColumnRegion(0, 0.0, page_width, page_width)], False

        # Exclude words wider than 35% of page (titles, author lines, equations)
        max_w = page_width * 0.35
        body = [w for w in cw if (w["x1"] - w["x0"]) <= max_w] or cw

        # x-midpoint histogram (5pt buckets)
        bucket = 5.0
        lo, hi = page_width * 0.35, page_width * 0.65
        start_b = int(lo / bucket) * bucket
        end_b = int(hi / bucket) * bucket
        hist: Dict[float, int] = {}
        curr = start_b
        while curr <= end_b:
            hist[round(curr, 2)] = 0
            curr += bucket

        for w in body:
            mid = (w["x0"] + w["x1"]) / 2
            b = round(int(mid / bucket) * bucket, 2)
            if b in hist:
                hist[b] += 1

        center = page_width / 2
        min_count = min(hist.values())
        min_buckets = [b for b, count in hist.items() if count == min_count]
        valley_b = min(min_buckets, key=lambda b: abs(b + bucket / 2 - center))
        split_x  = valley_b + bucket / 2   # center of valley bucket

        # Verify balance: each side must have ≥ 20% of body words
        n_left  = sum(1 for w in body if (w["x0"] + w["x1"]) / 2 < split_x)
        n_right = sum(1 for w in body if (w["x0"] + w["x1"]) / 2 >= split_x)
        total   = max(len(body), 1)
        if n_left / total < 0.20 or n_right / total < 0.20:
            x0 = min(w["x0"] for w in cw)
            x1 = max(w["x1"] for w in cw)
            return 0.0, [ColumnRegion(0, x0, x1, x1 - x0)], False

        # Compute column extents from words clearly on each side
        left_words  = [w for w in body if (w["x0"]+w["x1"])/2 < split_x]
        right_words = [w for w in body if (w["x0"]+w["x1"])/2 >= split_x]

        if not left_words or not right_words:
            x0 = min(w["x0"] for w in cw)
            x1 = max(w["x1"] for w in cw)
            return 0.0, [ColumnRegion(0, x0, x1, x1 - x0)], False

        lx0 = min(w["x0"] for w in left_words)
        lx1 = max(w["x1"] for w in left_words)
        rx0 = min(w["x0"] for w in right_words)
        rx1 = max(w["x1"] for w in right_words)

        # In a real two-column document, there MUST be a positive gutter (rx0 > lx1)
        # where no words cross between columns.
        if (rx0 - lx1) < 6.0:
            x0 = min(w["x0"] for w in cw)
            x1 = max(w["x1"] for w in cw)
            return 0.0, [ColumnRegion(0, x0, x1, x1 - x0)], False

        cols = [
            ColumnRegion(0, lx0, lx1, lx1 - lx0),
            ColumnRegion(1, rx0, rx1, rx1 - rx0),
        ]
        return split_x, cols, True

    # ------------------------------------------------------------------
    # Word-to-column assignment using the split boundary
    # ------------------------------------------------------------------

    def _split_words_by_column(
        self, words: list, split_x: float,
        page_width: float, page_height: float
    ) -> List[list]:
        """
        Split words into columns using the split_x boundary.
        Single-column pages (split_x == 0) return all words in one list.

        Enforces: a word never appears in two columns simultaneously.
        Assignment is by x-midpoint vs split_x.
        """
        if split_x == 0.0:
            return [sorted(words, key=lambda w: (w["top"], w["x0"]))]

        col0, col1 = [], []
        for w in words:
            mid = (w["x0"] + w["x1"]) / 2
            if mid < split_x:
                col0.append(w)
            else:
                col1.append(w)

        return [
            sorted(col0, key=lambda w: (w["top"], w["x0"])),
            sorted(col1, key=lambda w: (w["top"], w["x0"])),
        ]

    # ------------------------------------------------------------------
    # Main text block extraction
    # ------------------------------------------------------------------

    def _extract_text_blocks(
        self,
        page_obj,
        page_num: int,
        page_height: float,
        grammar: DocumentGrammar,
        ro: list,
        non_content: List[NonContentElement],
    ) -> Tuple[List[TextBlock], float, List[ColumnRegion]]:
        """
        Extract text blocks with correct multi-column reading order.

        Returns (blocks, split_x, columns).
        """
        words = page_obj.extract_words(
            extra_attrs=["fontname", "size"],
            use_text_flow=False,
            keep_blank_chars=False,
        )
        if not words:
            return [], 0.0, grammar.column_regions

        pw = float(page_obj.width)

        # Column split strategy:
        # If grammar established a two-column layout, use the grammar's split_x
        # consistently on ALL pages. Per-page detection is unreliable because
        # figures, captions, and other non-text elements distort the midpoint
        # histogram on individual pages.
        # Only fall back to per-page detection if grammar says single-column.
        if grammar.column_count == 2 and grammar.split_x > 0:
            split_x = grammar.split_x
            cols = grammar.column_regions
        else:
            split_x, cols, two_col = self._find_split(words, pw, page_height)
            if grammar.column_count == 1:
                split_x = 0.0
                cols = grammar.column_regions

        # On Page 1 with multi-column layout, detect top title/author header banner
        blocks: List[TextBlock] = []
        col_words_to_split = words

        if page_num == 1 and grammar.column_count == 2 and split_x > 0:
            body_size = grammar.body_fontsize
            col0_body = [
                w for w in words
                if (w["x0"] + w["x1"]) / 2 < split_x
                and (
                    float(w.get("size", body_size)) <= body_size * 1.05
                    or any(h in w["text"].lower() for h in ["abstract", "intro", "keywords"])
                )
            ]
            col1_body = [
                w for w in words
                if (w["x0"] + w["x1"]) / 2 >= split_x
                and float(w.get("size", body_size)) <= body_size * 1.05
            ]

            min_col0_y = min((w["top"] for w in col0_body), default=9999.0)
            min_col1_y = min((w["top"] for w in col1_body), default=9999.0)
            banner_threshold = min(min_col0_y, min_col1_y)

            if banner_threshold < 9999.0 and banner_threshold > 0:
                banner_words = [w for w in words if w["bottom"] <= banner_threshold + 1.0]
                col_words_to_split = [w for w in words if w["bottom"] > banner_threshold + 1.0]

                if banner_words:
                    banner_lines = self._group_words_into_lines(banner_words)
                    banner_paras = self._group_lines_into_paragraphs(banner_lines)
                    for para in banner_paras:
                        all_words = [w for line in para for w in line]
                        text = " ".join(w["text"] for w in all_words).strip()
                        if not text:
                            continue
                        x0 = min(w["x0"] for w in all_words)
                        y0 = min(w["top"] for w in all_words)
                        x1 = max(w["x1"] for w in all_words)
                        y1 = max(w["bottom"] for w in all_words)
                        bbox = BBox(x0, y0, x1, y1)
                        if self._overlaps_non_content(bbox, page_num, non_content):
                            continue
                        fnames = [w.get("fontname", "") for w in all_words]
                        sizes = [float(w.get("size", grammar.body_fontsize)) for w in all_words]
                        fontname = max(set(fnames), key=fnames.count)
                        fontsize = round(sum(sizes) / len(sizes), 1)
                        blocks.append(TextBlock(
                            text=text,
                            bbox=bbox,
                            page=page_num,
                            column=0,
                            fontname=fontname,
                            fontsize=fontsize,
                            is_bold="bold" in fontname.lower() or "Bold" in fontname,
                            is_heading=False,
                            reading_order=ro[0],
                            line_height=grammar.body_line_height,
                        ))
                        ro[0] += 1

        # Split words by column, maintaining strict separation
        col_word_lists = self._split_words_by_column(col_words_to_split, split_x, pw, page_height)
        for col_idx, col_words in enumerate(col_word_lists):
            if not col_words:
                continue

            # Filter out figure caption words (small font, clearly captions)
            # These contaminate heading lines when figures overlap text zones
            body_size = grammar.body_fontsize
            col_words_main = [
                w for w in col_words
                if float(w.get("size", body_size)) >= body_size * 0.75
            ]
            col_words_capts = [
                w for w in col_words
                if float(w.get("size", body_size)) < body_size * 0.75
            ]

            lines = self._group_words_into_lines(col_words_main)
            # Split lines at heading boundaries BEFORE paragraph grouping
            lines = self._split_lines_on_headings(lines, grammar)
            paragraphs = self._group_lines_into_paragraphs(lines)

            for para in paragraphs:
                all_words = [w for line in para for w in line]
                text = " ".join(w["text"] for w in all_words).strip()
                if not text:
                    continue

                x0 = min(w["x0"] for w in all_words)
                y0 = min(w["top"] for w in all_words)
                x1 = max(w["x1"] for w in all_words)
                y1 = max(w["bottom"] for w in all_words)
                bbox = BBox(x0, y0, x1, y1)

                if self._overlaps_non_content(bbox, page_num, non_content):
                    continue

                fnames = [w.get("fontname", "") for w in all_words]
                sizes  = [float(w.get("size", grammar.body_fontsize)) for w in all_words]
                fontname = max(set(fnames), key=fnames.count)
                fontsize = round(sum(sizes) / len(sizes), 1)
                is_bold  = "bold" in fontname.lower() or "Bold" in fontname
                is_hdg   = self._classify_heading(text, fontsize, is_bold, grammar)

                blocks.append(TextBlock(
                    text=text,
                    bbox=bbox,
                    page=page_num,
                    column=col_idx,
                    fontname=fontname,
                    fontsize=fontsize,
                    is_bold=is_bold,
                    is_heading=is_hdg,
                    reading_order=ro[0],
                    line_height=grammar.body_line_height,
                ))
                ro[0] += 1

        # Post-process: split blocks that still contain multiple headings
        blocks = self._split_merged_headings(blocks, grammar, ro)

        return blocks, split_x, cols

    # ------------------------------------------------------------------
    # Post-processing: split blocks that contain multiple headings
    # ------------------------------------------------------------------

    def _split_merged_headings(
        self, blocks: List[TextBlock], grammar: DocumentGrammar, ro: list
    ) -> List[TextBlock]:
        """
        Some PDFs render consecutive headings with no visual gap, causing
        the paragraph grouper to merge them into one block.
        Example: "V. EXPERIMENTAL EVALUATION A. Experimental Setup"
                 "Abstract —Retrieval-Augmented Generation..."

        This pass splits such blocks at heading boundaries detected in the text.

        Patterns that trigger a split:
          - Roman numeral heading pattern found after the first word
          - Alpha subsection pattern found after the first word
          - Known heading word appearing after body text
        """
        result: List[TextBlock] = []
        # Reassign reading_order from scratch after split
        current_ro = ro[0] - len(blocks)

        for block in blocks:
            parts = self._split_block_on_headings(block, grammar)
            for p_idx, (part_text, part_is_heading) in enumerate(parts):
                if len(parts) > 1 and part_is_heading:
                    # Heading part in a multi-part split is just the top line
                    lh = float(block.line_height or grammar.body_line_height or 12.0)
                    part_bbox = BBox(
                        block.bbox.x0,
                        block.bbox.y0,
                        block.bbox.x1,
                        min(block.bbox.y0 + lh * 1.5, block.bbox.y1),
                    )
                else:
                    part_bbox = block.bbox

                b = TextBlock(
                    text=part_text,
                    bbox=part_bbox,
                    page=block.page,
                    column=block.column,
                    fontname=block.fontname,
                    fontsize=block.fontsize,
                    is_bold=block.is_bold,
                    is_heading=part_is_heading,
                    reading_order=current_ro,
                    line_height=block.line_height,
                )
                result.append(b)
                current_ro += 1

        ro[0] = current_ro
        return result

    def _split_block_on_headings(
        self, block: TextBlock, grammar: DocumentGrammar
    ) -> List[Tuple[str, bool]]:
        """
        Split a block's text at internal heading boundaries.
        Returns list of (text, is_heading) tuples.
        """
        text = block.text

        # Find all positions in the text where a heading starts
        # We look for:
        #   1. Roman numeral pattern: \bI{1,3}V?\. or \bVI{0,3}\.  etc.
        #   2. Alpha subsection: \b[A-Z]\.\s+[A-Z]
        #   3. Known heading words at word boundaries (when preceded by space/newline)

        # Build list of split points (character positions)
        split_points = []

        # Roman numeral at non-start position
        for m in re.finditer(
            r'(?<!\A)(?<=\s)(' + _ROMAN + r'\.\s+[A-Z])', text
        ):
            split_points.append(m.start())

        # Alpha subsection at non-start position
        for m in re.finditer(r'(?<=\s)([A-Z]\.\s+[A-Z])', text):
            if m.start() > 0:
                split_points.append(m.start())

        # Known top-level heading words at start, followed by body text
        # e.g. "Abstract —Retrieval-Augmented..." → split after "Abstract —"
        for kh in ["abstract", "keywords", "index terms"]:
            # Match "Keyword— rest" or "Keyword: rest" at start of text
            m = re.match(
                r'^(' + re.escape(kh) + r'\s*[\u2014\-:—\s])',
                text, re.IGNORECASE
            )
            if m and len(text) > len(m.group(1)) + 20:
                # Only split if there's substantial body text after the heading
                split_points.append(len(m.group(1)))
                break
            # No internal splits needed
            is_hdg = self._classify_heading(
                text, block.fontsize, block.is_bold, grammar
            )
            return [(text, is_hdg)]

        split_points = sorted(set(split_points))

        parts = []
        prev = 0
        for sp in split_points:
            chunk = text[prev:sp].strip()
            if chunk:
                is_hdg = self._classify_heading(chunk, block.fontsize, block.is_bold, grammar)
                parts.append((chunk, is_hdg))
            prev = sp

        # Last chunk
        chunk = text[prev:].strip()
        if chunk:
            is_hdg = self._classify_heading(chunk, block.fontsize, block.is_bold, grammar)
            parts.append((chunk, is_hdg))

        return parts if parts else [(text, block.is_heading)]

    def _is_heading_line(self, line_text: str, grammar: DocumentGrammar) -> bool:
        t = line_text.strip()
        if not t or len(t) < 2:
            return False
        tn = re.sub(r'(?<=[A-Z]) (?=[A-Z])', '', t)

        if _ROMAN_HEADING_RE.match(t) or _ROMAN_HEADING_RE.match(tn):
            return True
        if _ALPHA_HEADING_RE.match(t) and len(t.split()) <= 8:
            return True
        if _TASK_NUMBER_RE.match(t) and len(t.split()) <= 10:
            return True
        if _KEYWORD_RE.match(tn):
            return True
        bare = tn.lower().rstrip('.:—\u2014 ')
        if bare in KNOWN_HEADINGS:
            return True
        words = t.split()
        letters = [c for c in tn if c.isalpha()]
        if letters and all(c.isupper() for c in letters) and 1 <= len(words) <= 8:
            if "PAGE " not in t and "PAGE" not in words and "HTTP" not in t and "@" not in t:
                return True
        return False

    def _split_lines_on_headings(self, lines: list, grammar: DocumentGrammar) -> list:
        """
        Insert None sentinels before any line whose text starts with a
        heading pattern, and split lines that contain an embedded heading
        mid-text (e.g. "body text VI. DISCUSSION").
        """
        result = []
        for line in lines:
            if not line:
                continue
            # Split line at embedded Roman-numeral heading mid-text
            sub_lines = self._split_line_at_embedded_heading(line)
            for sub in sub_lines:
                if not sub:
                    continue
                line_text = " ".join(w["text"] for w in sub).strip()
                is_hdg_line = self._is_heading_line(line_text, grammar)
                if is_hdg_line and result and result[-1] is not None:
                    result.append(None)   # force paragraph break before heading
                result.append(sub)
                if is_hdg_line:
                    result.append(None)   # force paragraph break after heading too
        return result

    def _split_line_at_embedded_heading(self, line: list) -> list:
        """
        If a line contains a Roman-numeral or alpha-subsection heading token
        after body text, split the line at that point.
        """
        if len(line) <= 1:
            return [line]

        sorted_words = sorted(line, key=lambda w: w["x0"])

        for i in range(1, len(sorted_words)):
            remaining = sorted_words[i:]
            text_from_here = " ".join(w["text"] for w in remaining)
            tn = re.sub(r'(?<=[A-Z]) (?=[A-Z])', '', text_from_here)

            is_heading_start = bool(
                _ROMAN_HEADING_RE.match(text_from_here) or
                _ROMAN_HEADING_RE.match(tn) or
                (_ALPHA_HEADING_RE.match(text_from_here) and len(text_from_here.split()) <= 6)
            )

            if is_heading_start:
                before = sorted_words[:i]
                after  = sorted_words[i:]
                if before and " ".join(w["text"] for w in before).strip():
                    return [before, after]

        return [sorted_words]

    def _group_words_into_lines(self, words: list, tolerance: float = 3.0) -> list:
        """Group words with approximately the same top coordinate into lines."""
        if not words:
            return []
        # words are already sorted by (top, x0) from _split_words_by_column
        lines, current, current_top = [], [words[0]], words[0]["top"]
        for w in words[1:]:
            if abs(w["top"] - current_top) <= tolerance:
                current.append(w)
            else:
                lines.append(sorted(current, key=lambda w: w["x0"]))
                current = [w]
                current_top = w["top"]
        if current:
            lines.append(sorted(current, key=lambda w: w["x0"]))
        return lines

    def _group_lines_into_paragraphs(self, lines: list) -> list:
        """
        Group lines into paragraphs using adaptive gap thresholding.

        Normal body-text lines have near-zero leading gaps (~1pt).
        Paragraph and heading breaks have larger gaps (5-15pt).
        Threshold = max(median_gap × 2.5, 3pt).
        """
        if not lines:
            return []
        if len(lines) == 1:
            return [lines]

        # Filter out sentinels (None), record forced break positions
        clean_lines = []
        forced_breaks: set = set()
        for item in lines:
            if item is None:
                forced_breaks.add(len(clean_lines))
            else:
                clean_lines.append(item)
        lines = clean_lines

        if not lines:
            return []
        if len(lines) == 1:
            return [lines]

        gaps = []
        for i in range(1, len(lines)):
            pb = max(w["bottom"] for w in lines[i - 1])
            ct = min(w["top"]    for w in lines[i])
            gaps.append(ct - pb)

        pos_gaps    = sorted(g for g in gaps if g >= 0)
        median_gap  = pos_gaps[len(pos_gaps) // 2] if pos_gaps else 1.0
        threshold   = max(median_gap * 2.5, 3.0)

        paras, current = [], [lines[0]]
        for i, line in enumerate(lines[1:]):
            is_forced = (i + 1) in forced_breaks
            is_gap    = gaps[i] > threshold
            if is_forced or is_gap:
                paras.append(current)
                current = [line]
            else:
                current.append(line)
        if current:
            paras.append(current)
        return paras

    # ------------------------------------------------------------------
    # Heading classification
    # ------------------------------------------------------------------

    def _classify_heading(
        self, text: str, fontsize: float, is_bold: bool,
        grammar: DocumentGrammar
    ) -> bool:
        t = text.strip()
        if self._is_heading_line(t, grammar):
            return True
        if fontsize > grammar.body_fontsize + 1.5 and is_bold:
            return True
        return False

    # ------------------------------------------------------------------
    # Non-content detection
    # ------------------------------------------------------------------

    def _extract_non_content(
        self, page_obj, page_num: int
    ) -> List[NonContentElement]:
        elements = []
        pw, ph = float(page_obj.width), float(page_obj.height)
        for img in page_obj.images:
            elements.append(NonContentElement(
                type="image", page=page_num,
                bbox=BBox(float(img["x0"]), float(img["top"]),
                          float(img["x1"]), float(img["bottom"])),
            ))
        for tbl in page_obj.find_tables():
            b = tbl.bbox
            tb = BBox(float(b[0]), float(b[1]), float(b[2]), float(b[3]))
            # Ignore false-positive page border/margin tables that cover > 70% of page area
            if tb.area >= (pw * ph * 0.70):
                continue
            elements.append(NonContentElement(
                type="table", page=page_num,
                bbox=tb,
            ))
        return elements

    def _overlaps_non_content(
        self, bbox: BBox, page_num: int,
        non_content: List[NonContentElement]
    ) -> bool:
        for elem in non_content:
            if elem.page != page_num:
                continue
            if bbox.overlaps(elem.bbox):
                ox = max(0.0, min(bbox.x1, elem.bbox.x1) - max(bbox.x0, elem.bbox.x0))
                oy_b0, oy_b1 = min(bbox.y0,bbox.y1), max(bbox.y0,bbox.y1)
                oe_b0, oe_b1 = min(elem.bbox.y0,elem.bbox.y1), max(elem.bbox.y0,elem.bbox.y1)
                oy = max(0.0, min(oy_b1, oe_b1) - max(oy_b0, oe_b0))
                if bbox.area > 0 and (ox * oy) / bbox.area > 0.5:
                    return True
        return False


    # ------------------------------------------------------------------
    # pymupdf text replacement pass
    # ------------------------------------------------------------------

    def _replace_text_with_pymupdf(
        self, pdf_path: str, all_blocks: List[TextBlock]
    ) -> None:
        """
        Replace each block's text with pymupdf's extraction.

        Uses column-aware clipping: restrict x range to the block's column
        to avoid cross-column text bleeding (the root cause of Abstract disappearing).
        """
        import fitz

        doc = fitz.open(pdf_path)

        for block in all_blocks:
            page_idx = block.page - 1
            if page_idx < 0 or page_idx >= len(doc):
                continue

            page = doc[page_idx]
            page_w = float(page.rect.width)

            # Clip to the block's column half to prevent cross-column bleeding
            if block.column == 0:
                clip_x0 = 0.0
                clip_x1 = page_w * 0.50
            else:
                clip_x0 = page_w * 0.50
                clip_x1 = page_w

            rect = fitz.Rect(
                clip_x0,
                block.bbox.y0,
                clip_x1,
                block.bbox.y1,
            )

            text = page.get_text("text", clip=rect).strip()

            if text:
                text = " ".join(text.split("\n"))
                text = " ".join(text.split())
                # Only replace body text blocks — heading blocks are short
                # and correct from pdfplumber; replacing them causes Abstract
                # to re-merge with its body text
                if not block.is_heading:
                    # Strip known heading prefixes that pymupdf picks up
                    # when heading and body share the same y-position
                    import re as _re
                    text = _re.sub(
                        r'^(Abstract|Keywords?|Index\s+Terms)[—\-:—\s]+',
                        '', text, flags=_re.IGNORECASE
                    ).strip()
                    if text:
                        block.text = text

        doc.close()


def analyze_pdf(pdf_path: str) -> AnalyzedDocument:
    return PDFAnalyzer().analyze(pdf_path)
