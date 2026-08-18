import argparse
import json
from html import escape
from pathlib import Path


def render_press_kit_html(press_kit: dict, language: str = "en") -> str:
    fact_sheet = press_kit["fact_sheet"]
    descriptions = press_kit["descriptions"]
    history = press_kit["history_and_inspiration"]
    features_html = "".join(f"<li>{escape(feature)}</li>" for feature in press_kit["features"])
    awards_html = "".join(
        f"<li><strong>{escape(str(a['year']))}</strong> — {escape(a['name'])}</li>"
        for a in press_kit["awards"]
    )
    coverage_html = "".join(
        f"<li><strong>{escape(c['publication'])}</strong> — {escape(c['headline'])}</li>"
        for c in press_kit["coverage"]
    )
    assets_html = "".join(
        "<tr>"
        f"<td>{escape(a['filename'])}</td>"
        f"<td>{escape(a['type'])}</td>"
        f"<td>{escape(a['caption'])}</td>"
        f"<td>{escape(a['credit'])}</td>"
        "</tr>"
        for a in press_kit["asset_index"]
    )
    platforms = ", ".join(escape(p) for p in fact_sheet["platforms"])

    return f'''<!DOCTYPE html>
<html lang="{escape(language)}">
<head>
<meta charset="UTF-8">
<title>{escape(press_kit["title"])} — Press Kit</title>
<style>
body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 0 auto; padding: 40px; line-height: 1.6; color: #222; }}
h1 {{ font-size: 42px; margin-bottom: 5px; }}
h2 {{ margin-top: 40px; border-bottom: 2px solid #222; padding-bottom: 8px; }}
h3 {{ margin-top: 25px; }}
.subtitle {{ color: #666; font-size: 18px; }}
.fact-sheet {{ display: grid; grid-template-columns: 180px 1fr; gap: 10px; background: #f5f5f5; padding: 20px; border-radius: 8px; }}
.fact-label {{ font-weight: bold; }}
.description-box {{ padding: 15px; border-left: 4px solid #333; margin: 15px 0; }}
blockquote {{ margin: 20px 0; padding: 20px; background: #f5f5f5; border-left: 5px solid #333; font-size: 20px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; vertical-align: top; }}
th {{ background: #f5f5f5; }}
</style>
</head>
<body>
<h1>{escape(press_kit["title"])}</h1>
<p class="subtitle">Official Game Press Kit</p>
<h2>Fact Sheet</h2>
<div class="fact-sheet">
<div class="fact-label">Studio</div><div>{escape(fact_sheet["studio"])}</div>
<div class="fact-label">Release Date</div><div>{escape(fact_sheet["release_date"])}</div>
<div class="fact-label">Platforms</div><div>{platforms}</div>
<div class="fact-label">Price</div><div>{escape(fact_sheet["price"])}</div>
<div class="fact-label">Availability</div><div>{escape(fact_sheet["availability"])}</div>
</div>
<h2>Description</h2>
<h3>One Line</h3><div class="description-box">{escape(descriptions["one_line"])}</div>
<h3>One Paragraph</h3><div class="description-box">{escape(descriptions["one_paragraph"])}</div>
<h3>Long Form</h3><div class="description-box">{escape(descriptions["long_form"])}</div>
<h2>Features</h2><ul>{features_html}</ul>
<h2>History &amp; Inspiration</h2>
<h3>History</h3><p>{escape(history["history"])}</p>
<h3>Inspiration</h3><p>{escape(history["inspiration"])}</p>
<h2>Verbatim Quote</h2>
<blockquote>&quot;{escape(press_kit["quote"]["text"])}&quot;<br><strong>— {escape(press_kit["quote"]["attribution"])}</strong></blockquote>
<h2>Awards</h2><ul>{awards_html}</ul>
<h2>Coverage</h2><ul>{coverage_html}</ul>
<h2>Asset Index</h2>
<p>The following index describes every supplied press asset.</p>
<table><thead><tr><th>Filename</th><th>Type</th><th>Caption</th><th>Credit</th></tr></thead><tbody>{assets_html}</tbody></table>
</body>
</html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a press kit JSON file as HTML.")
    parser.add_argument("--input", default="output/emberfall_press_kit.json")
    parser.add_argument("--output", default="output/emberfall_press_kit.html")
    parser.add_argument("--language", default="en")
    args = parser.parse_args()
    press_kit = json.loads(Path(args.input).read_text(encoding="utf-8"))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_press_kit_html(press_kit, args.language), encoding="utf-8")
    print(f"HTML press kit created: {output}")


if __name__ == "__main__":
    main()
