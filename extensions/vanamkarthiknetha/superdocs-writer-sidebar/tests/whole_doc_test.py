"""Whole-document write-back test (headless Linux, OFFLINE - no key, 0 operations).

Exercises writeback.apply_changes with a synthetic pending-changes list against
a real Writer document, proving the write-back invariants the sidebar relies on:

  1. a unique single-paragraph match is replaced in place, styles intact
  2. a multi-paragraph run is matched as ONE range and replaced
  3. an ambiguous match (duplicate text) is SKIPPED, both copies untouched
  4. text not in the document is SKIPPED
  5. table-cell content is out of scope -> SKIPPED, table untouched
  6. everything not matched stays exactly as it was

Run via run_whole_doc_test.sh (starts the headless office this connects to).
"""
import sys
import time
from pathlib import Path

import uno

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "pythonpath"))
import writeback


def connect(retries=40):
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local)
    for _ in range(retries):
        try:
            return resolver.resolve(
                "uno:socket,host=localhost,port=2003;urp;StarOffice.ComponentContext")
        except Exception:
            time.sleep(2)
    raise RuntimeError("could not connect to soffice on port 2003")


ctx = connect()
smgr = ctx.ServiceManager
desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
doc = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, ())
text = doc.getText()
cursor = text.createTextCursor()

BODY = "The vendor shall deliver the report by friday, probably."
RUN_A = "First step of the rollout."
RUN_B = "Second step of the rollout."
DUP = "This sentence appears twice."


def para(style, content):
    cursor.ParaStyleName = style
    text.insertString(cursor, content, False)
    text.insertControlCharacter(cursor, 0, False)  # PARAGRAPH_BREAK


para("Heading 1", "Contract Summary")
para("Standard", BODY)
para("Standard", RUN_A)
para("Standard", RUN_B)
para("Standard", DUP)
para("Standard", DUP)
table = doc.createInstance("com.sun.star.text.TextTable")
table.initialize(1, 2)
cursor.ParaStyleName = "Standard"
text.insertTextContent(cursor, table, False)
table.getCellByName("A1").setString("Owner")
table.getCellByName("B1").setString("Legal team")

pending = [
    # 1. unique single paragraph -> applied (entities + inline tags on purpose)
    {"change_id": "c1",
     "old_html": f"<p>{BODY}</p>",
     "new_html": "<p>The vendor shall deliver the report by <b>Friday&nbsp;17:00</b>.</p>"},
    # 2. two consecutive paragraphs -> ONE range, collapsed to one paragraph
    {"change_id": "c2",
     "old_html": f"<p>{RUN_A}</p><p>{RUN_B}</p>",
     "new_html": "<p>Both rollout steps, merged.</p>"},
    # 3. ambiguous -> skipped
    {"change_id": "c3",
     "old_html": f"<p>{DUP}</p>",
     "new_html": "<p>should never land</p>"},
    # 4. not in document -> skipped
    {"change_id": "c4",
     "old_html": "<p>text that exists nowhere in this file</p>",
     "new_html": "<p>should never land</p>"},
    # 5. table cell -> out of scope, skipped
    {"change_id": "c5",
     "old_html": "<p>Owner</p>",
     "new_html": "<p>should never land</p>"},
]

results = writeback.apply_changes(doc, pending)
by_id = {r["change_id"]: r for r in results}

paras = []
enum = text.createEnumeration()
while enum.hasMoreElements():
    p = enum.nextElement()
    if p.supportsService("com.sun.star.text.Paragraph"):
        paras.append((p.ParaStyleName, p.getString()))
texts = [p[1] for p in paras]

checks = [
    ("c1 applied", by_id["c1"]["applied"]),
    ("c1 text landed (entities decoded, tags stripped)",
     "The vendor shall deliver the report by Friday 17:00." in texts),
    ("c1 kept Standard style",
     any(s == "Standard" and t.startswith("The vendor shall deliver")
         for s, t in paras)),
    ("c2 applied", by_id["c2"]["applied"]),
    ("c2 run collapsed to one paragraph",
     texts.count("Both rollout steps, merged.") == 1
     and RUN_A not in texts and RUN_B not in texts),
    ("c3 skipped as ambiguous", not by_id["c3"]["applied"]
     and "ambiguous" in by_id["c3"]["reason"]),
    ("c3 both duplicates untouched", texts.count(DUP) == 2),
    ("c4 skipped as not found", not by_id["c4"]["applied"]),
    ("c5 skipped (table out of scope)", not by_id["c5"]["applied"]),
    ("table untouched",
     [table.getCellByName(n).getString() for n in ("A1", "B1")] == ["Owner", "Legal team"]),
    ("heading untouched", paras[0] == ("Heading 1", "Contract Summary")),
    ("nothing bogus landed", "should never land" not in texts),
]

# ---- draft insertion (v0.3.1): insert_paragraphs never touches existing text ----
before_texts = list(texts)
n_end = writeback.insert_paragraphs(doc, ["Draft alpha.", "Draft beta."])       # at end
heading_para = None
enum = text.createEnumeration()
while enum.hasMoreElements():
    p = enum.nextElement()
    if p.supportsService("com.sun.star.text.Paragraph") and p.getString() == "Contract Summary":
        heading_para = p
        break
n_mid = writeback.insert_paragraphs(doc, ["Inserted after heading."], heading_para)

paras2 = []
enum = text.createEnumeration()
while enum.hasMoreElements():
    p = enum.nextElement()
    if p.supportsService("com.sun.star.text.Paragraph"):
        paras2.append((p.ParaStyleName, p.getString()))
texts2 = [t for _, t in paras2]
nonempty2 = [t for t in texts2 if t.strip()]

checks += [
    ("insert at end returned 2", n_end == 2),
    ("draft paragraphs landed at end", nonempty2[-2:] == ["Draft alpha.", "Draft beta."]),
    ("insert at range returned 1", n_mid == 1),
    ("mid insert landed right after heading",
     texts2[texts2.index("Contract Summary") + 1] == "Inserted after heading."),
    ("heading text/style survived insertion", paras2[0] == ("Heading 1", "Contract Summary")),
    # non-empty only: inserting at the end legitimately consumes the trailing
    # EMPTY paragraph (writing into an empty paragraph touches no content)
    ("every pre-insert non-empty paragraph still present in order",
     [t for t in texts2 if t.strip() and t in before_texts]
     == [t for t in before_texts if t.strip()]),
    ("table survived insertion",
     [table.getCellByName(n).getString() for n in ("A1", "B1")] == ["Owner", "Legal team"]),
]

ok = True
for name, passed in checks:
    print(("PASS " if passed else "FAIL ") + name)
    ok = ok and passed
doc.close(False)
print("WHOLE-DOC WRITE-BACK TEST:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
