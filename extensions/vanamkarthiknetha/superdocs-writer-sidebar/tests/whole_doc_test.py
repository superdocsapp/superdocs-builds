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
    # 6. pure insertion into a NON-empty doc -> position is a guess, skipped
    {"change_id": "c6",
     "old_html": "",
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
    ("c6 pure insertion skipped in non-empty doc", not by_id["c6"]["applied"]
     and "pure insertion" in by_id["c6"]["reason"]),
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

# ---- empty-doc drafting (v0.3.4): whole-doc mode on an EMPTY document ----
# Server-side drafting returns pending changes that are all pure insertions
# (no old_html). With no existing content to misplace them against, they must
# be appended in job order — not skipped ("Applied 0 of 11" on an empty doc).
doc2 = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, ())
empty_pending = [
    {"change_id": "e1", "old_html": "", "new_html": "<h1>Fitness Plan</h1>"},
    {"change_id": "e2", "old_html": None, "new_html": "<p>Day 1: Push.</p><p>Day 2: Pull.</p>"},
    {"change_id": "e3", "old_html": "", "new_html": "<p>Day 3: Legs.</p>"},
    {"change_id": "e4", "old_html": "", "new_html": ""},   # nothing to insert
]
empty_results = writeback.apply_changes(doc2, empty_pending)
empty_by_id = {r["change_id"]: r for r in empty_results}
texts3 = []
enum = doc2.getText().createEnumeration()
while enum.hasMoreElements():
    p = enum.nextElement()
    if p.supportsService("com.sun.star.text.Paragraph") and p.getString().strip():
        texts3.append(p.getString())

checks += [
    ("empty doc: all insertions applied",
     all(empty_by_id[c]["applied"] for c in ("e1", "e2", "e3"))),
    ("empty doc: reason says appended",
     "appended" in empty_by_id["e1"]["reason"]),
    ("empty doc: draft reconstructed in job order",
     texts3 == ["Fitness Plan", "Day 1: Push.", "Day 2: Pull.", "Day 3: Legs."]),
    ("empty doc: change with no content skipped",
     not empty_by_id["e4"]["applied"]),
]
doc2.close(False)

# ---- full-rewrite rescue (v0.3.5): delete-everything + pure insertions ----
# A rewrite of a NON-empty doc arrives as one deletion covering the whole old
# content plus pure insertions carrying the new content. The deletion applied
# and the insertions were skipped -> old text wiped, replacement dropped
# ("Applied 1 of 11", empty doc). Once approved deletions EMPTY the doc, the
# rescue pass must append the skipped insertions in job order - wherever they
# sat relative to the deletion in the batch.
doc3 = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, ())
t3 = doc3.getText()
cur3 = t3.createTextCursor()
t3.insertString(cur3, "Old Plan", False)
t3.insertControlCharacter(cur3, 0, False)  # PARAGRAPH_BREAK
t3.insertString(cur3, "Monday: cardio.", False)
rewrite_pending = [
    # insertion BEFORE the deletion in job order - rescued all the same
    {"change_id": "r1", "old_html": "", "new_html": "<h1>Weight Gain Plan</h1>"},
    {"change_id": "r2", "old_html": "<p>Old Plan</p><p>Monday: cardio.</p>",
     "new_html": ""},
    {"change_id": "r3", "old_html": "", "new_html": "<p>Monday: squats.</p>"},
]
rw = {r["change_id"]: r for r in writeback.apply_changes(doc3, rewrite_pending)}
texts4 = []
enum = doc3.getText().createEnumeration()
while enum.hasMoreElements():
    p = enum.nextElement()
    if p.supportsService("com.sun.star.text.Paragraph") and p.getString().strip():
        texts4.append(p.getString())

checks += [
    ("rewrite: whole-doc deletion applied", rw["r2"]["applied"]),
    ("rewrite: insertions rescued on both sides of the delete",
     rw["r1"]["applied"] and rw["r3"]["applied"]
     and "appended" in rw["r1"]["reason"]),
    ("rewrite: doc rebuilt in job order, old content gone",
     texts4 == ["Weight Gain Plan", "Monday: squats."]),
]
doc3.close(False)

# partial deletion: the doc still has content -> insertions must STAY skipped
doc4 = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, ())
t4 = doc4.getText()
cur4 = t4.createTextCursor()
t4.insertString(cur4, "Keep me.", False)
t4.insertControlCharacter(cur4, 0, False)
t4.insertString(cur4, "Delete me.", False)
partial_pending = [
    {"change_id": "p1", "old_html": "<p>Delete me.</p>", "new_html": ""},
    {"change_id": "p2", "old_html": "", "new_html": "<p>should never land</p>"},
]
pr = {r["change_id"]: r for r in writeback.apply_changes(doc4, partial_pending)}
texts5 = []
enum = doc4.getText().createEnumeration()
while enum.hasMoreElements():
    p = enum.nextElement()
    if p.supportsService("com.sun.star.text.Paragraph") and p.getString().strip():
        texts5.append(p.getString())

checks += [
    ("partial delete: deletion applied", pr["p1"]["applied"]),
    ("partial delete: pure insertion still skipped (doc kept content)",
     not pr["p2"]["applied"] and "pure insertion" in pr["p2"]["reason"]),
    ("partial delete: kept paragraph untouched", texts5 == ["Keep me."]),
]
doc4.close(False)

ok = True
for name, passed in checks:
    print(("PASS " if passed else "FAIL ") + name)
    ok = ok and passed
doc.close(False)
print("WHOLE-DOC WRITE-BACK TEST:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
