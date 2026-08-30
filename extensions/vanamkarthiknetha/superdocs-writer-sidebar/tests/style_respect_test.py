"""Styled-document respect test (headless Linux, costs 1 operation).

Builds a Writer doc with Heading 1 + body + bullet list + table, edits ONE body
paragraph through the same client + setString path the sidebar panel uses, then
asserts every style survived and nothing else changed.

Run via run_style_test.sh (starts the headless office this connects to).
"""
import sys
import time
from pathlib import Path

import uno

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "pythonpath"))
import superdocs_client as sc


def connect(retries=40):
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local)
    for _ in range(retries):
        try:
            return resolver.resolve(
                "uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext")
        except Exception:
            time.sleep(2)
    raise RuntimeError("could not connect to soffice on port 2002")


ctx = connect()
smgr = ctx.ServiceManager
desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
doc = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, ())
text = doc.getText()
cursor = text.createTextCursor()

SLOPPY = "we gonna move the db next week, dont worry bout downtime it should be fine probably."

# Style names differ across LibreOffice generations ("List Bullet" family was
# dropped around LO 26; bullets are "List 1".."List 5"). Discover, don't assume.
pstyles = doc.getStyleFamilies().getByName("ParagraphStyles")
_names = list(pstyles.getElementNames())
_candidates = ([n for n in _names if "bullet" in n.lower()]
               + [n for n in ("List 1", "List") if n in _names])
if not _candidates:
    print("no bullet/list style; available:", _names)
    sys.exit(2)
BULLET = _candidates[0]
print("using bullet style:", BULLET)

# heading
cursor.ParaStyleName = "Heading 1"
text.insertString(cursor, "Migration Plan", False)
text.insertControlCharacter(cursor, 0, False)  # PARAGRAPH_BREAK
# body paragraph (the edit target)
cursor.ParaStyleName = "Standard"
text.insertString(cursor, SLOPPY, False)
text.insertControlCharacter(cursor, 0, False)
# bullet list
cursor.ParaStyleName = BULLET
text.insertString(cursor, "Backup verification", False)
text.insertControlCharacter(cursor, 0, False)
text.insertString(cursor, "Rollback rehearsal", False)
text.insertControlCharacter(cursor, 0, False)
# table
table = doc.createInstance("com.sun.star.text.TextTable")
table.initialize(2, 2)
cursor.ParaStyleName = "Standard"
text.insertTextContent(cursor, table, False)
table.getCellByName("A1").setString("Owner")
table.getCellByName("B1").setString("DBA team")
table.getCellByName("A2").setString("Window")
table.getCellByName("B2").setString("Sat 02:00")

# locate the sloppy paragraph and select it as a range
target = None
enum = text.createEnumeration()
while enum.hasMoreElements():
    para = enum.nextElement()
    if para.supportsService("com.sun.star.text.Paragraph") and para.getString() == SLOPPY:
        target = para
        break
assert target is not None, "target paragraph not found"

rng = text.createTextCursorByRange(target.getStart())
rng.gotoEndOfParagraph(True)

print("1) requesting edit via sidebar client ...")
edit = sc.request_edit(rng.getString(), "Rewrite formally and precisely.",
                       progress=lambda m: print("   ", m))
assert edit["state"] == "awaiting_approval", edit["state"]
final = sc.finalize(edit, True, progress=lambda m: print("   ", m))
print("   final:", final[:120])
rng.setString(final)  # exactly what the panel's write_back does

# ---- assertions ----
results = []
paras = []
enum = text.createEnumeration()
while enum.hasMoreElements():
    p = enum.nextElement()
    if p.supportsService("com.sun.star.text.Paragraph"):
        paras.append((p.ParaStyleName, p.getString()))

results.append(("heading style intact", paras[0] == ("Heading 1", "Migration Plan")))
results.append(("edited para kept Default style", paras[1][0] == "Standard"))
results.append(("edited para text changed", paras[1][1] != SLOPPY and len(paras[1][1]) > 10))
bullets = [p for p in paras if p[0] == BULLET]
results.append(("both bullets intact",
                [b[1] for b in bullets] == ["Backup verification", "Rollback rehearsal"]))
cells = [table.getCellByName(n).getString() for n in ("A1", "B1", "A2", "B2")]
results.append(("table cells untouched", cells == ["Owner", "DBA team", "Window", "Sat 02:00"]))

ok = True
for name, passed in results:
    print(("PASS " if passed else "FAIL ") + name)
    ok = ok and passed
doc.close(False)
print("STYLE TEST:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
