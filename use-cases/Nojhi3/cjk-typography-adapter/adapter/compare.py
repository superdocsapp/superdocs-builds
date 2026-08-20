import difflib
import html

from .htmltree import Node, collect_blocks


def _diff_cells(a: str, b: str) -> str:
    sm = difflib.SequenceMatcher(None, a, b)
    left, right = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            chunk = html.escape(a[i1:i2])
            left.append(chunk)
            right.append(chunk)
        elif op == "replace":
            left.append(f'<del class="chg-del">{html.escape(a[i1:i2])}</del>')
            right.append(f'<ins class="chg-ins">{html.escape(b[j1:j2])}</ins>')
        elif op == "delete":
            left.append(f'<del class="chg-del">{html.escape(a[i1:i2])}</del>')
        else:
            right.append(f'<ins class="chg-ins">{html.escape(b[j1:j2])}</ins>')
    return "".join(left), "".join(right)


def build_comparison(original_tree: Node, adapted_tree: Node, title: str) -> str:
    orig = collect_blocks(original_tree)
    adap = collect_blocks(adapted_tree)
    sm = difflib.SequenceMatcher(None, orig, adap)
    rows = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for a, b in zip(orig[i1:i2], adap[j1:j2]):
                rows.append((html.escape(a), html.escape(b)))
        elif op == "replace":
            a_chunks, b_chunks = _diff_cells(orig[i1], adap[j1])
            rows.append((a_chunks, b_chunks))
            for a in orig[i1 + 1:i2]:
                rows.append((f'<del class="chg-del">{html.escape(a)}</del>', ""))
            for b in adap[j1 + 1:j2]:
                rows.append(("", f'<ins class="chg-ins">{html.escape(b)}</ins>'))
        elif op == "delete":
            for a in orig[i1:i2]:
                rows.append((f'<del class="chg-del">{html.escape(a)}</del>', ""))
        else:
            for b in adap[j1:j2]:
                rows.append(("", f'<ins class="chg-ins">{html.escape(b)}</ins>'))
    body = "\n".join(
        f"<tr><td class='orig'>{l}</td><td class='adap'>{r}</td></tr>"
        for l, r in rows
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} - side by side</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 24px; color: #1a1a1a; }}
  h1 {{ font-size: 18px; }}
  .note {{ color: #666; font-size: 13px; margin-bottom: 16px; }}
  table.compare {{ border-collapse: collapse; width: 100%; table-layout: fixed; }}
  .compare td {{ width: 50%; vertical-align: top; border: 1px solid #ddd; padding: 10px 14px;
                 font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }}
  .orig {{ background: #fafafa; }}
  .adap {{ background: #f2f8f0; }}
  .chg-del {{ background: #ffd7d7; color: #a00; text-decoration: line-through; }}
  .chg-ins {{ background: #d6f0d6; color: #0a6b0a; }}
  .label {{ font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em;
           color: #555; border: 1px solid #ddd; border-bottom: none; padding: 6px 14px; background: #f0f0f0; }}
</style>
</head>
<body>
<h1>{html.escape(title)} - side by side</h1>
<div class="note">Original (left) vs adapted (right). Removed: red strikethrough, added: green.</div>
<table class="compare">
<tr><th class="label">Original</th><th class="label">Adapted</th></tr>
{body}
</table>
</body>
</html>
"""
