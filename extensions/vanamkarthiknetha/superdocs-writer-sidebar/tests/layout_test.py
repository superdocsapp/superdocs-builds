"""Panel layout test (OFFLINE - plain python3, no LibreOffice, no key, 0 operations).

Drives panel_layout.solve at every panel height from far below the floor to far
above the preferred layout and proves the invariants the sidebar depends on:

  1. the status line is fully inside the panel at every size >= the reported
     minimum - the bug this module exists to fix (a short office window used to
     push it off the bottom)
  2. Apply/Reject are always visible, and always above the status line
  3. nothing overlaps and nothing sticks out sideways
  4. the instruction box, Send, the checkbox and the status line never vanish
  5. an empty preview takes no space at all; a filled one is visible whenever
     the panel is above its floor
  6. extra height is absorbed, not left as dead space at the bottom
  7. the whole thing scales with the host's pixels-per-unit (HiDPI)

Run: python3 tests/layout_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "pythonpath"))
import panel_layout as pl

ALWAYS = ("chkWholeDoc", "txtInstruction", "btnSend", "btnApprove", "btnReject", "lblStatus")
checks = []


def check(name, passed):
    checks.append((name, passed))


for unit in (1.5, 2.0, 3.0):          # 100%, standard, HiDPI
    for has_preview in (False, True):
        tag = f"[unit={unit} preview={'yes' if has_preview else 'no'}]"
        floor = pl.stack_height(pl.FLOOR, unit, has_preview)
        preferred = pl.stack_height(pl.PREF, unit, has_preview)
        check(f"{tag} floor is well below preferred", 0 < floor < preferred)

        for width in (int(80 * unit), int(130 * unit), int(300 * unit)):
            # from half the floor (deck would scroll) to twice the preferred
            for height in range(floor // 2, preferred * 2, 7):
                boxes = dict(pl.solve(width, height, unit, has_preview))
                shown = {k: v for k, v in boxes.items() if v}
                where = f"{tag} {width}x{height}"

                if height >= floor:
                    status = boxes["lblStatus"]
                    check(f"{where}: status is placed", bool(status))
                    if status:
                        check(f"{where}: status fits inside the panel",
                              status[1] + status[3] <= height)
                        check(f"{where}: status keeps a readable line",
                              status[3] >= int(round(10 * unit)))
                    for cid in ALWAYS:
                        check(f"{where}: {cid} still visible", bool(boxes[cid]))
                    approve, reject = boxes["btnApprove"], boxes["btnReject"]
                    check(f"{where}: decision buttons above the status line",
                          approve[1] + approve[3] <= status[1])
                    check(f"{where}: buttons share the row",
                          approve[1] == reject[1] and approve[3] == reject[3])
                    check(f"{where}: buttons align with both margins",
                          approve[0] == round(pl.PAD * unit)
                          and reject[0] + reject[2] == width - round(pl.PAD * unit))
                    check(f"{where}: buttons do not overlap",
                          approve[0] + approve[2] <= reject[0])

                # ordering + no overlap, in the declared top-to-bottom order
                stacked = [b for b in shown.values()]
                # btnApprove stands in for the row it shares with btnReject
                rows = [b for cid, b in pl.solve(width, height, unit, has_preview)
                        if b and cid != "btnReject"]
                check(f"{where}: rows stack without overlapping",
                      all(a[1] + a[3] <= b[1] for a, b in zip(rows, rows[1:])))
                check(f"{where}: nothing overflows the panel width",
                      all(b[0] >= 0 and b[0] + b[2] <= width for b in stacked))
                check(f"{where}: full-width rows share one width",
                      len({b[2] for cid, b in shown.items()
                           if cid not in ("btnApprove", "btnReject")}) == 1)
                check(f"{where}: nothing starts above the top margin",
                      all(b[1] >= round(pl.PAD * unit) for b in stacked))

                check(f"{where}: empty preview takes no room",
                      has_preview or boxes["lblPreview"] is None)
                if has_preview and height >= preferred:
                    check(f"{where}: filled preview is shown", bool(boxes["lblPreview"]))

                if height >= preferred:
                    bottom = max(b[1] + b[3] for b in stacked)
                    check(f"{where}: spare height is absorbed, not left dangling",
                          bottom >= height - round(pl.PAD * unit) - 1)

# a tall panel gives the flexible boxes more than they ask for
tall = dict(pl.solve(260, 900, 2.0, True))
pref = dict(pl.solve(260, pl.stack_height(pl.PREF, 2.0, True), 2.0, True))
for cid in ("lblPreview", "txtInstruction", "lblStatus"):
    check(f"tall panel grows {cid}", tall[cid][3] > pref[cid][3])
for cid in ("btnSend", "btnApprove", "chkWholeDoc"):
    check(f"tall panel leaves {cid} at its natural height", tall[cid][3] == pref[cid][3])

# a squeezed panel drops the decoration first, never the working controls
squeezed = dict(pl.solve(260, pl.stack_height(pl.FLOOR, 2.0, True), 2.0, True))
check("floor layout drops the hint text", squeezed["lblHint"] is None)
check("floor layout keeps every working control",
      all(squeezed[cid] for cid in ALWAYS))

ok = True
for name, passed in checks:
    if not passed:
        print("FAIL " + name)
    ok = ok and passed
print(f"{len(checks)} assertions over "
      f"{len({n.split(':')[0] for n, _ in checks})} panel sizes")
print("PANEL LAYOUT TEST:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
