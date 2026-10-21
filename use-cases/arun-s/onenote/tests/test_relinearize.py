"""Proof the re-linearizer reads the CANVAS, not the DOM order — the 'what strong
looks like' case: two side-by-side text boxes and an inline image, delivered by the
API out of visual order. Keyless."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from relinearize import parse_blocks, rows, to_reading_order_html

# The API returns these OUT of reading order on purpose:
#   right-top box first, then the bottom footer, then the left-top box, then a middle image.
PAGE = """
<html><body data-absolute-enabled="true">
  <div style="position:absolute;left:400px;top:96px;width:280px"><h2>Right column</h2><p>Beta text.</p></div>
  <div style="position:absolute;left:48px;top:520px;width:600px"><p>Footer note.</p></div>
  <div style="position:absolute;left:48px;top:96px;width:280px"><h2>Left column</h2><p>Alpha text.</p></div>
  <img src="https://example/img1.png" style="position:absolute;left:48px;top:320px;width:400px"/>
</body></html>
"""


def test_blocks_are_extracted_with_coordinates():
    blocks = parse_blocks(PAGE)
    assert len(blocks) == 4
    imgs = [b for b in blocks if b.kind == "image"]
    assert len(imgs) == 1 and imgs[0].src.endswith("img1.png")


def test_rows_cluster_side_by_side_boxes_together():
    r = rows(parse_blocks(PAGE))
    # row 1 = the two top boxes (left then right), row 2 = image, row 3 = footer
    assert len(r) == 3
    assert [b.kind for b in r[0]] == ["text", "text"]
    assert r[0][0].left < r[0][1].left                 # left column before right column
    assert r[1][0].kind == "image"


def test_reading_order_differs_from_dom_order():
    out = to_reading_order_html(PAGE, title="My Page")
    # reading order must be: Left, Right, image, Footer
    assert out.index("Left column") < out.index("Right column") < out.index("img1.png") < out.index("Footer note")
    # ...which is NOT the DOM order the API gave (Right, Footer, Left, image)
    dom = PAGE
    assert dom.index("Right column") < dom.index("Footer note") < dom.index("Left column")
    # headings survived, ready for a clean docx
    assert "<h2>Left column</h2>" in out and "<h1>My Page</h1>" in out
