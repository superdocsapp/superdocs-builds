# Editing a Word document from Python without touching the formatting

**Part one of three. Connect to SuperDocs and make your first real edit, in about fifteen minutes.**

By the end of this you will have a Python script that opens a contract, inserts a
new clause into it, and proves that the rest of the document came back untouched.
No pip install, no framework, about ninety lines.

I am writing this as a candidate working through the SuperDocs Round 2 task, and
everything below was run against the live API before it was written down. Where
the API did something I did not expect, it says so.

## Who this is for

Python developers who have a document problem rather than a text problem. The
distinction matters more than it sounds.

If you need words generated, any model does that. What is hard is the other job:
you already have a fifty page agreement with numbered clauses, a pricing table
and a compliance matrix, and you need clause 4 changed and nothing else moved. A
chat window hands you a paragraph and leaves you to paste it back in by hand. The
whole point of a document API is that the edit lands in the document.

## Prerequisites

- Python 3.10 or newer. Check with `python3 --version`.
- A SuperDocs account from [use.superdocs.app](https://use.superdocs.app). There
  is no guest mode.
- An API key from your account settings. It starts with `sk_`.
- Nothing else. Every example in this series uses the standard library only.

```bash
export SUPERDOCS_API_KEY=sk_your_key_here
```

Put it in your shell, not in your code. Part three has more to say about that.

## The three calls

The whole of part one is three HTTP calls.

| Call | What it is for |
| --- | --- |
| `GET /v1/agents/whoami` | Your tier and how many operations you have left. Free. |
| `POST /v1/sessions/init` | Opens a session. The session holds the document. |
| `POST /v1/chat` | The edit. One billable operation per document changing turn. |

Auth is a bearer token on every call:

```python
headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
```

### Check what you have before you spend it

```python
import json, os, urllib.request

BASE = "https://api.superdocs.app"
KEY = os.environ["SUPERDOCS_API_KEY"]

def call(path, payload=None, method="POST"):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=body, method=method,
        headers={"Authorization": f"Bearer {KEY}",
                 "Content-Type": "application/json",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())

me = call("/v1/agents/whoami", method="GET")
print(me["tier"], me["quota"]["remaining"], "operations left")
```

An edit is one operation. An operation covers up to twenty five sections changed
in a single request, so it goes further than the number suggests. Exports and
uploads are free. Only the AI actually changing the document costs anything.

One thing worth knowing early: if your account is running on a promotional
allowance, `whoami` reports your base monthly quota and it does not move as you
spend. The real number is in the `usage` block that comes back on each edit,
under `promotions`. If you are writing an agent that stops when it runs low,
read the number on the response, not the one on `whoami`.

### Open a session

```python
session_id = call("/v1/sessions/init", {})["session_id"]
```

A session is where the document lives across turns. You send the document once
and then talk about it. Re-sending the HTML on every turn is the most common
waste in a first integration.

### Make the edit

```python
original = open("service-agreement.html").read()

result = call("/v1/chat", {
    "session_id": session_id,
    "message": "Insert a new section titled 'Confidentiality' immediately after "
               "section 3, and renumber the sections that follow it. ... "
               "Change nothing else. Leave the charges table exactly as it is.",
    "document_html": original,        # first turn only
    "response_mode": "full",
})

edited = result["document_changes"]["updated_html"]
print(result["document_changes"]["changes_summary"])
print(result["usage"]["ops_charged"], "operation")
```

Two notes on the message, both of which changed my results:

**Say what must not change.** "Leave the charges table exactly as it is" is doing
real work. Without it, the table is fair game.

**Pass the document in `document_html`, do not describe it.** If you put your
content in the message and ask the AI to reproduce it, it authors it again and it
drifts. `document_html` is a verbatim load.

The call takes fifteen to twenty seconds on a short document. A quiet terminal is
the model working. Resending gets you charged twice.

## The part everyone skips

The response tells you it succeeded. That is not the same as it being right.

Here is the check, and it is the reason this tutorial exists:

```python
import re

def strip_chunk_ids(html):
    return re.sub(r'\s*data-chunk-id="[^"]*"', "", html)

def visible_text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
```

**Why `strip_chunk_ids` has to exist.** Your document goes in as plain HTML and
comes back with a `data-chunk-id` on every element:

```html
<h2 data-chunk-id="c45a1bf4-b4cc-4e46-a9ac-2bc09ffc1a28">1. Scope of services</h2>
```

Those IDs are how you address one paragraph later, so they are a feature, not
noise. But if you diff the raw strings you will conclude that every section
changed, and you will be wrong. Compare the visible text instead.

With that in place, compare section by section:

```python
before, after = sections(original), sections(edited)
unchanged = [h for h in before
             if visible_text(after.get(match(h), "")) == visible_text(before[h])]
print(f"{len(unchanged)} of {len(before)} sections kept their text exactly")
```

Run [`part1_first_edit/first_edit.py`](../part1_first_edit/first_edit.py) and
this is the real output:

```
account   c5e0bfdc  tier free  500 of 500 operations left
session   session_init_299271d8cf6b
editing   (a quiet wait here is the model working, not a hang)
charged   1 operation, 500 left
summary   2 sections edited, 1 added, rest untouched

added     ['4. Confidentiality']
unchanged 4 of 5 original sections kept their text exactly
changed   ['3. Charges and payment']
table     5 rows before, 5 after
table     attributes changed on the round trip: {' border="1" cellpadding="6" cellspacing="0"'} -> {''}
PLACEMENT ['3. Charges and payment']   <-- new content landed inside this section,
          between its heading and its own text
```

The summary line said "rest untouched" and the document says otherwise. Two
things happened that the response would never have told me about.

### The clause landed in the wrong place

I asked for the new section after section 3. It arrived between section 3's
heading and section 3's own paragraph:

```html
<h2>3. Charges and payment</h2>
<div><h2>4. Confidentiality</h2><p>Each party shall keep ...</p></div>
<p>Charges are invoiced monthly in arrears ...</p>
<table> ... </table>
```

The text is correct. The renumbering is correct: Service levels became 5,
Governing law became 6. It is anchored to the heading rather than placed after
the section's last element, so section 3 now has a clause wedged inside it and
its own paragraph sits under someone else's heading.

**And it does not happen every time.** I ran the same script against the same
document six times: four runs misplaced the section, two got it right. That is
the most useful part of this whole tutorial. If the failure were reliable you
would find it on your first run and never ship it. Because it is intermittent,
you can build the integration, test it twice, see it work twice, and ship a
document generator that quietly gets it wrong a third of the time. The check is
not paranoia, it is the only thing standing between you and that. On screen in a summary this
looks fine. On paper it is a contract with a clause in the wrong clause.

That is the check earning its place: seventeen lines of regex caught something
the API's own summary called untouched. It is written up with reproduction steps
in FINDINGS.md, in the shape SuperDocs asks bug reports to take.

### The table lost its attributes

`<table border="1" cellpadding="6" cellspacing="0">` came back as `<table>`, with
a `<tbody>` added. All five rows survived, every cell value survived, and the
export still renders as a table with borders because the docx renderer applies
its own styling. But if you round trip HTML you author yourself and you rely on
presentational attributes, check them. Structure is preserved. Inline
presentational attributes on the table element are not.

Neither of these makes the API unfit. They make the case for the same thing:
verify placement, do not verify vibes.

## Getting a Word file out

Export is free and takes the session or ad-hoc HTML:

```python
payload = {"session_id": session_id, "format": "docx", "filename": "agreement.docx"}
```

One gotcha that cost me twenty minutes. The published OpenAPI schema describes a
JSON response for `/v1/documents/export`. The endpoint actually returns the file
bytes with a `content-disposition` header. If you call `json.loads` on it you get
a `JSONDecodeError` full of `PK\x03\x04`, which is the first two bytes of a zip,
because a .docx is a zip. Read the body as bytes and write it to disk:

```python
req = urllib.request.Request(f"{BASE}/v1/documents/export", data=body,
                             method="POST", headers={**headers, "Accept": "*/*"})
with urllib.request.urlopen(req, timeout=600) as resp:
    open("agreement.docx", "wb").write(resp.read())
```

Formats: `docx`, `pdf`, `html`, `markdown`, `txt`.

## Run it

```bash
git clone <this repo>
cd superdocs-python-tutorials
export SUPERDOCS_API_KEY=sk_...
python3 sample/make_samples.py
python3 part1_first_edit/first_edit.py
```

You get `out/service-agreement.edited.html` and `out/service-agreement.docx`,
one operation spent, and a verdict on whether the edit went where you asked.

The sample contract is invented. Northwind Facilities Group and Harbour Lane
Analytics do not exist, and no real agreement belongs in a tutorial you are
about to run.

## What part two fixes

Part one applies the edit and then inspects it. When the placement is wrong, it
is already wrong in your document, and your only move is another billable turn
to undo it.

That is backwards for anything that matters. [Part two](part-2-review-gate.md)
puts a human in front of the edit: the AI proposes each change with a diff, you
approve or deny it, denied changes never touch the document, and feedback goes
back for a revision. It is the same misplaced clause, caught before it lands.

---

*Written by Rushikesh Vaidya as part of the SuperDocs Round 2 task. Code:
[github.com/vaidyarushikesh7/superdocs-python-tutorials](https://github.com/vaidyarushikesh7/superdocs-python-tutorials)*
