"""Check line gaps on page 1 to tune paragraph splitting."""
import sys, os
sys.path.insert(0, 'service')
import pdfplumber
from pdf_analyzer import PDFAnalyzer
from collections import Counter

pdf_path = [os.path.join('demo', f) for f in os.listdir('demo') if f.endswith('.pdf')][0]

with pdfplumber.open(pdf_path) as pdf:
    for page_num in [0, 1]:  # pages 1 and 2
        page = pdf.pages[page_num]
        pw, ph = float(page.width), float(page.height)
        words = page.extract_words(extra_attrs=['fontname','size'], use_text_flow=False)
        content = [w for w in words if ph*0.05 < w['top'] < ph*0.95]

        analyzer = PDFAnalyzer()
        cols, gap = analyzer._detect_columns_from_words(content, pw, ph)
        print(f"\n=== Page {page_num+1}: {len(cols)} columns, gap={gap:.1f} ===")
        for c in cols:
            print(f"  col {c.index}: x0={c.x0:.0f} x1={c.x1:.0f}")

        # For each column, show line-by-line top values and gaps
        for col in cols:
            col_words = [w for w in content
                         if (w['x0']+w['x1'])/2 >= col.x0
                         and (w['x0']+w['x1'])/2 <= col.x1]
            col_words.sort(key=lambda w: (w['top'], w['x0']))
            lines = analyzer._group_words_into_lines(col_words, tolerance=3.0)

            print(f"\n  Col {col.index} — {len(lines)} lines:")
            prev_bot = None
            for i, line in enumerate(lines):
                top = min(w['top'] for w in line)
                bot = max(w['bottom'] for w in line)
                gap_from_prev = top - prev_bot if prev_bot is not None else 0
                text = ' '.join(w['text'] for w in line)
                flag = " <-- GAP" if gap_from_prev > 5 else ""
                print(f"    {i:3d}  top={top:6.1f} gap={gap_from_prev:5.1f}  '{text[:55]}'{flag}")
                prev_bot = bot
            
            # Show gap distribution
            gaps = []
            prev_bot = None
            for line in lines:
                top = min(w['top'] for w in line)
                bot = max(w['bottom'] for w in line)
                if prev_bot is not None:
                    gaps.append(round(top - prev_bot, 1))
                prev_bot = bot
            if gaps:
                gap_dist = Counter(gaps)
                print(f"\n  Gap distribution (col {col.index}):")
                for g, cnt in sorted(gap_dist.items()):
                    print(f"    gap={g:5.1f}  count={cnt}")
