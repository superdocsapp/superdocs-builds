import sys, os
sys.path.insert(0, 'service')
import pdfplumber

pdf_path = [os.path.join('demo', f) for f in os.listdir('demo') if f.endswith('.pdf')][0]
with pdfplumber.open(pdf_path) as pdf:
    page = pdf.pages[0]
    pw, ph = float(page.width), float(page.height)
    words = page.extract_words(extra_attrs=['fontname','size'], use_text_flow=False)
    content = [w for w in words if ph*0.05 < w['top'] < ph*0.95]

    # Try gutter at split 50%
    split_x = pw * 0.50
    left  = [w for w in content if (w['x0']+w['x1'])/2 < split_x]
    right = [w for w in content if (w['x0']+w['x1'])/2 >= split_x]
    print(f"Split at {split_x:.0f}: left={len(left)}, right={len(right)}")
    if left and right:
        lx1 = max(w['x1'] for w in left)
        rx0 = min(w['x0'] for w in right)
        print(f"  left max x1  = {lx1:.1f}")
        print(f"  right min x0 = {rx0:.1f}")
        print(f"  gutter       = {rx0 - lx1:.1f}pt")

    # Find culprit wide words
    print("\nTop 10 widest words in content zone:")
    for w in sorted(content, key=lambda w: w['x1']-w['x0'], reverse=True)[:10]:
        mid = (w['x0']+w['x1'])/2
        sz = float(w.get('size', 0))
        print(f"  x0={w['x0']:6.1f} x1={w['x1']:6.1f} mid={mid:6.1f} top={w['top']:6.1f} size={sz:.1f}  '{w['text']}'")

    # Try body-text-only detection (exclude large font title words)
    body_sizes = [float(w.get('size',10)) for w in content]
    from collections import Counter
    body_size = Counter(round(s,1) for s in body_sizes).most_common(1)[0][0]
    print(f"\nbody_size = {body_size}")
    body_words = [w for w in content if abs(float(w.get('size',10)) - body_size) < 1.5]
    print(f"Body-text-only words: {len(body_words)}")

    if body_words:
        split_x = pw * 0.50
        left2  = [w for w in body_words if (w['x0']+w['x1'])/2 < split_x]
        right2 = [w for w in body_words if (w['x0']+w['x1'])/2 >= split_x]
        if left2 and right2:
            lx1 = max(w['x1'] for w in left2)
            rx0 = min(w['x0'] for w in right2)
            print(f"Body-only split at {split_x:.0f}: left={len(left2)}, right={len(right2)}")
            print(f"  left max x1  = {lx1:.1f}")
            print(f"  right min x0 = {rx0:.1f}")
            print(f"  gutter       = {rx0 - lx1:.1f}pt")
