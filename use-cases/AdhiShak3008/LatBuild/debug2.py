"""Diagnose exactly why column detection fails on this PDF."""
import sys, os
sys.path.insert(0, 'service')
import pdfplumber

PDF_PATH = [os.path.join('demo', f) for f in os.listdir('demo') if f.endswith('.pdf')][0]

with pdfplumber.open(PDF_PATH) as pdf:
    page = pdf.pages[0]
    pw, ph = float(page.width), float(page.height)
    words = page.extract_words(extra_attrs=["fontname", "size"], use_text_flow=False)

    content_words = [w for w in words if ph * 0.07 < w['top'] < ph * 0.93]
    print(f"Content words (after header/footer filter): {len(content_words)}")

    # Show x0 distribution
    bucket_size = 5.0
    hist = {}
    for w in content_words:
        bucket = int(w['x0'] / bucket_size) * bucket_size
        hist[bucket] = hist.get(bucket, 0) + 1

    print(f"\nx0 histogram (bucket=5pt, top 30 buckets by frequency):")
    for k in sorted(hist.keys()):
        bar = '#' * hist[k]
        print(f"  x0={k:6.1f}  count={hist[k]:3d}  {bar}")

    print(f"\npage_width={pw}, mid_start={pw*0.25:.1f}, mid_end={pw*0.75:.1f}")

    mid_start = pw * 0.25
    mid_end   = pw * 0.75
    occupied = sorted(k for k in hist if mid_start <= k <= mid_end)
    print(f"Occupied x0 buckets in middle zone: {occupied}")

    if len(occupied) > 1:
        prev = occupied[0]
        best_gap = 0
        best_center = None
        for x in occupied[1:]:
            g = x - prev
            if g > best_gap:
                best_gap = g
                best_center = (prev + x) / 2
            prev = x
        print(f"Best gap: {best_gap:.1f}pt at center x={best_center:.1f}")
        print(f"10% threshold: {pw*0.10:.1f}pt")
        print(f"Gap passes threshold: {best_gap > pw * 0.10}")

    # Show where the actual column boundary should be
    print(f"\nActual x0 range: {min(w['x0'] for w in content_words):.1f} to {max(w['x0'] for w in content_words):.1f}")
    left_words  = [w for w in content_words if w['x0'] < pw/2]
    right_words = [w for w in content_words if w['x0'] >= pw/2]
    print(f"Words with x0 < {pw/2:.0f}: {len(left_words)}")
    print(f"Words with x0 >= {pw/2:.0f}: {len(right_words)}")
    if left_words:
        print(f"Left max x1: {max(w['x1'] for w in left_words):.1f}")
    if right_words:
        print(f"Right min x0: {min(w['x0'] for w in right_words):.1f}")
