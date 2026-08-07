"""Whole-document LIVE round-trip test (headless Linux, costs 1 operation).

The offline test (whole_doc_test.py) proves the write-back mechanics; this one
proves the integration: a real Writer doc exported as .docx through the host
filter, sent through request_doc_edit, approved, and written back range by
range from the ACTUAL old_html/new_html SuperDocs returned.

Needs SUPERDOCS_API_KEY or ~/.superdocs/agent_credentials.json.
Run via run_whole_doc_live_test.sh.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

import uno
import unohelper
from com.sun.star.beans import PropertyValue

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "pythonpath"))
import superdocs_client as sc
import writeback


def connect(retries=40):
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local)
    for _ in range(retries):
        try:
            return resolver.resolve(
                "uno:socket,host=localhost,port=2004;urp;StarOffice.ComponentContext")
        except Exception:
            time.sleep(2)
    raise RuntimeError("could not connect to soffice on port 2004")


ctx = connect()
desktop = ctx.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
doc = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, ())
text = doc.getText()
cursor = text.createTextCursor()

TARGET = "The supplier will try to deliver stuff sometime soon, no promises."
KEEP = "Payment terms are net thirty days from the invoice date."


def para(style, content):
    cursor.ParaStyleName = style
    text.insertString(cursor, content, False)
    text.insertControlCharacter(cursor, 0, False)  # PARAGRAPH_BREAK


para("Heading 1", "Service Agreement")
para("Standard", TARGET)
para("Standard", KEEP)
table = doc.createInstance("com.sun.star.text.TextTable")
table.initialize(1, 2)
cursor.ParaStyleName = "Standard"
text.insertTextContent(cursor, table, False)
table.getCellByName("A1").setString("Owner")
table.getCellByName("B1").setString("Procurement")

# export exactly the way the panel does
fd, path = tempfile.mkstemp(suffix=".docx")
os.close(fd)
prop = PropertyValue()
prop.Name = "FilterName"
prop.Value = "MS Word 2007 XML"
doc.storeToURL(unohelper.systemPathToFileUrl(path), (prop,))
with open(path, "rb") as f:
    docx_bytes = f.read()
os.remove(path)
print(f"1) exported {len(docx_bytes)} bytes, requesting whole-doc edit ...")

edit = sc.request_doc_edit(
    docx_bytes,
    "Rewrite the vague delivery sentence into a formal commitment to deliver "
    "within 10 business days. Leave every other part of the document unchanged.",
    progress=lambda m: print("   ", m))
assert edit["state"] == "awaiting_approval", edit["state"]
for c in edit["pending"]:
    print("   pending old:", (c.get("old_html") or "")[:100])
    print("   pending new:", (c.get("new_html") or "")[:100])

print("2) approving ...")
sc.finalize(edit, True, progress=lambda m: print("   ", m), want_text=False)

print("3) writing back range by range ...")
results = writeback.apply_changes(doc, edit["pending"])
for r in results:
    print("   ", r)

paras = []
enum = text.createEnumeration()
while enum.hasMoreElements():
    p = enum.nextElement()
    if p.supportsService("com.sun.star.text.Paragraph"):
        paras.append((p.ParaStyleName, p.getString()))
texts = [t for _, t in paras]

checks = [
    ("at least one change applied", any(r["applied"] for r in results)),
    ("vague sentence gone", TARGET not in texts),
    ("replacement kept Standard style",
     all(s == "Standard" for s, t in paras if TARGET[:20] not in t and t not in
         ("Service Agreement",) and t.strip())),
    ("untouched paragraph identical", KEEP in texts),
    ("heading untouched", paras[0] == ("Heading 1", "Service Agreement")),
    ("table untouched",
     [table.getCellByName(n).getString() for n in ("A1", "B1")] == ["Owner", "Procurement"]),
]

ok = True
for name, passed in checks:
    print(("PASS " if passed else "FAIL ") + name)
    ok = ok and passed
doc.close(False)
print("WHOLE-DOC LIVE TEST:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
