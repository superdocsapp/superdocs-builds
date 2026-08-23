"""Trace the exact extraction of page 10 col1 to find where VI. DISCUSSION goes."""
import sys, os, re
sys.path.insert(0, 'service')
import pdfplumber
from pdf_analyzer import PDFAnalyzer, DocumentGrammar, _ROMAN_HEADING_RE, _ALPHA_HEADING_RE

pdf_path = [os.path.join('demo', f) for f in os.listdir('demo') if f.endswith('.pdf')][0]

analyzer = PDFAnalyzer()

with pdfplumber.open(pdf_path) as pdf:
    grammar = analyzer._extract_grammar(pdf)
    page_obj = pdf.pages[9]  # page 10
    ph = float(page_obj.height)
    pw = float(page_obj.width)
    
    words = page_obj.extract_words(extra_attrs=['fontname','size'], use_text_flow=False)
    split_x, cols, two_col = analyzer._find_split(words, pw, ph)
    print(f"split_x={split_x:.1f}, cols={len(cols)}")
    
    col_word_lists = analyzer._split_words_by_column(words, split_x, pw, ph)
    col1_words = col_word_lists[1] if len(col_word_lists) > 1 else []
    print(f"col1 words: {len(col1_words)}")
    
    # Show lines
    lines = analyzer._group_words_into_lines(col1_words)
    print(f"\ncol1 lines ({len(lines)} total), focused on top 420-600:")
    for i, line in enumerate(lines):
        top = min(w['top'] for w in line)
        bot = max(w['bottom'] for w in line)
        text = ' '.join(w['text'] for w in line)
        tn = re.sub(r'(?<=[A-Z]) (?=[A-Z])', '', text)
        is_roman = bool(_ROMAN_HEADING_RE.match(text) or _ROMAN_HEADING_RE.match(tn))
        is_alpha = bool(_ALPHA_HEADING_RE.match(text))
        if 400 < top < 620:
            flag = "[ROMAN]" if is_roman else "[ALPHA]" if is_alpha else "      "
            print(f"  {flag} line {i:3d}  top={top:6.1f} bot={bot:6.1f}  '{text[:70]}'")
    
    # Show with heading splitter applied
    print(f"\nAfter _split_lines_on_headings:")
    marked = analyzer._split_lines_on_headings(lines, grammar)
    para_count = 0
    for item in marked:
        if item is None:
            para_count += 1
    print(f"  Sentinels inserted: {para_count}")
    
    # Show paragraphs
    paras = analyzer._group_lines_into_paragraphs(marked)
    print(f"\nParagraphs ({len(paras)} total), top 400-620:")
    for i, para in enumerate(paras):
        all_words = [w for line in para for w in line]
        top = min(w['top'] for w in all_words)
        bot = max(w['bottom'] for w in all_words)
        text = ' '.join(w['text'] for w in all_words)
        tn = re.sub(r'(?<=[A-Z]) (?=[A-Z])', '', text)
        is_hdg = analyzer._classify_heading(text, 10.0, False, grammar)
        if 400 < top < 620:
            print(f"  {'[H]' if is_hdg else '   '} para {i:2d}  top={top:5.1f} bot={bot:5.1f}  '{text[:70]}'")
