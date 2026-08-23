"""
debug_pipeline.py
Instrument the extraction pipeline stage by stage.
Run from LatBuild/ folder.
"""
import sys, os
sys.path.insert(0, 'service')
import pdfplumber

PDF_PATH = None
for f in sorted(os.listdir('demo')):
    if f.endswith('.pdf'):
        PDF_PATH = os.path.join('demo', f)
        break

if not PDF_PATH:
    print("No PDF in demo/"); sys.exit(1)

print(f"PDF: {PDF_PATH}\n")

PAGE_NUM = 1  # 1-indexed — inspect page 1

with pdfplumber.open(PDF_PATH) as pdf:
    page = pdf.pages[PAGE_NUM - 1]
    pw, ph = float(page.width), float(page.height)
    print(f"Page {PAGE_NUM}: {pw:.1f} x {ph:.1f} pts\n")

    # ---------------------------------------------------------------
    # STAGE 1: raw words from pdfplumber
    # ---------------------------------------------------------------
    words_flow = page.extract_words(
        extra_attrs=["fontname", "size"],
        use_text_flow=True,
    )
    words_no_flow = page.extract_words(
        extra_attrs=["fontname", "size"],
        use_text_flow=False,
    )
    print(f"STAGE 1 — raw words (use_text_flow=True):  {len(words_flow)} words")
    print(f"STAGE 1 — raw words (use_text_flow=False): {len(words_no_flow)} words")
    print()

    # Show first 20 words with coordinates
    print("First 20 words (no_flow), sorted by (top, x0):")
    for w in sorted(words_no_flow, key=lambda w: (w['top'], w['x0']))[:20]:
        print(f"  x0={w['x0']:6.1f} top={w['top']:6.1f} x1={w['x1']:6.1f} bot={w['bottom']:6.1f}"
              f"  size={w.get('size',0):4.1f}  '{w['text']}'")
    print()

    # ---------------------------------------------------------------
    # STAGE 2: column detection
    # ---------------------------------------------------------------
    from pdf_analyzer import PDFAnalyzer, DocumentGrammar, ColumnRegion
    analyzer = PDFAnalyzer()

    content_words = [w for w in words_no_flow
                     if ph * 0.07 < w['top'] < ph * 0.93]
    cols, gap = analyzer._detect_columns_from_words(content_words, pw, ph)
    print(f"STAGE 2 — columns detected: {len(cols)}, gap={gap:.1f}")
    for c in cols:
        print(f"  col {c.index}: x0={c.x0:.1f}  x1={c.x1:.1f}  width={c.width:.1f}")
    print()

    # ---------------------------------------------------------------
    # STAGE 3: word→column assignment
    # ---------------------------------------------------------------
    words_by_col = {i: [] for i in range(len(cols))}
    for w in words_no_flow:
        col_idx = analyzer._assign_word_to_column(w, cols)
        words_by_col[col_idx].append(w)

    for col_idx, col_words in words_by_col.items():
        print(f"STAGE 3 — col {col_idx}: {len(col_words)} words")
        for w in sorted(col_words, key=lambda w: w['top'])[:8]:
            print(f"  top={w['top']:6.1f}  '{w['text']}'")
    print()

    # ---------------------------------------------------------------
    # STAGE 4: line grouping per column
    # ---------------------------------------------------------------
    # Need grammar for line_height — estimate from page
    all_sizes = [float(w.get('size', 10)) for w in words_no_flow]
    body_size = max(set(round(s, 1) for s in all_sizes),
                   key=lambda s: all_sizes.count(s)) if all_sizes else 10.0
    line_height = body_size * 1.3

    print(f"STAGE 4 — body_fontsize={body_size}, line_height={line_height:.1f}")
    for col_idx in sorted(words_by_col.keys()):
        col_words = sorted(words_by_col[col_idx], key=lambda w: (w['top'], w['x0']))
        lines = analyzer._group_words_into_lines(col_words, tolerance=3.0)
        print(f"  col {col_idx}: {len(lines)} lines")
        for i, line in enumerate(lines[:6]):
            text = ' '.join(w['text'] for w in line)
            top = min(w['top'] for w in line)
            print(f"    line {i:2d}  top={top:6.1f}  '{text[:70]}'")
    print()

    # ---------------------------------------------------------------
    # STAGE 5: paragraph grouping per column
    # ---------------------------------------------------------------
    print("STAGE 5 — paragraphs per column:")
    for col_idx in sorted(words_by_col.keys()):
        col_words = sorted(words_by_col[col_idx], key=lambda w: (w['top'], w['x0']))
        lines = analyzer._group_words_into_lines(col_words, tolerance=3.0)
        paras = analyzer._group_lines_into_paragraphs(lines, line_height)
        print(f"  col {col_idx}: {len(paras)} paragraphs (line_height={line_height:.1f})")
        for i, para in enumerate(paras[:8]):
            words_in_para = [w for line in para for w in line]
            text = ' '.join(w['text'] for w in words_in_para)
            top = min(w['top'] for w in words_in_para)
            bot = max(w['bottom'] for w in words_in_para)
            print(f"    para {i:2d}  top={top:5.1f} bot={bot:5.1f}  '{text[:70]}'")
    print()

    # ---------------------------------------------------------------
    # STAGE 6: full analyze_pdf output — how many blocks total on page 1?
    # ---------------------------------------------------------------
    from pdf_analyzer import analyze_pdf
    doc = analyze_pdf(PDF_PATH)
    page1_blocks = [b for b in doc.all_blocks if b.page == 1]
    print(f"STAGE 6 — analyze_pdf() blocks on page 1: {len(page1_blocks)}")
    print(f"          total blocks all pages: {len(doc.all_blocks)}")
    for b in page1_blocks:
        flag = "[H]" if b.is_heading else "   "
        print(f"  {flag} col={b.column} y0={b.bbox.y0:6.1f}  '{b.text[:70]}'")
    print()

    # ---------------------------------------------------------------
    # STAGE 7: flow_mapper sections
    # ---------------------------------------------------------------
    from flow_mapper import build_flow_map
    fm = build_flow_map(doc)
    print(f"STAGE 7 — sections: {len(fm.sections)}")
    for s in fm.sections:
        pages_str = str(s.pages[0]) if len(s.pages) == 1 else f"{s.pages[0]}-{s.pages[-1]}"
        print(f"  [{' E' if s.is_editable else '  '}] {s.name[:40]:<40} pages={pages_str:<8} words={s.word_count}")
