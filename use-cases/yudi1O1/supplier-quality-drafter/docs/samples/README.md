# Raw output from the live two-template run

These two files are **committed raw data**, not illustrations: they are the exact
markdown exports SuperDocs returned when `scripts/demo_two_templates.py` drafted
the *same* `examples/sample_input_complete.yaml` onto two different synthetic
customer templates.

They are here so the content-parity claim in the README can be checked by anyone,
without an API key and without spending an operation:

| File | Template used | Session |
| --- | --- | --- |
| `demo-template-a.md` | `templates/customer_template_a.html` (Acme Automotive Systems) | `demo-two-templates-a` |
| `demo-template-b.md` | `templates/customer_template_b.html` (Meridian Powertrain Co.) | `demo-two-templates-b` |

## Method (stated before the result)

`demo_two_templates.py` derives the list of facts to check **from the input data
model**, not from the output text: every failure-mode id, every S/O/D rating,
every computed RPN, every action id and target date, the PPAP part number and
submission level, and the 8D root cause. Each is then required to appear verbatim
in both exports. Deliberately *not* a raw digit-scan of the two files — each
template's own boilerplate contains numbers too (template A's instructions say
"1-10 AIAG-VDA scale", template B's don't), and those are presentation, not data.

## Result

27 facts checked, 0 missing from either export.

## What legitimately differs between the two files

Section order (template B leads with the 8D report, template A leads with the
FMEA), headings, the customer's own instruction paragraphs, and the footer. That
is the point: presentation follows the customer's template, content does not move.

## Verify it yourself, offline

```bash
python - <<'PY'
import re
a = open("docs/samples/demo-template-a.md", encoding="utf-8").read()
b = open("docs/samples/demo-template-b.md", encoding="utf-8").read()
row = re.compile(r"\|\s*(FM-\d+)\s*\|.*?\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|")
for name, text in (("A", a), ("B", b)):
    for fm, s, o, d, rpn in row.findall(text):
        assert int(s) * int(o) * int(d) == int(rpn), (name, fm)
        print(f"template {name}  {fm}: {s}x{o}x{d} == {rpn}  OK")
PY
```
