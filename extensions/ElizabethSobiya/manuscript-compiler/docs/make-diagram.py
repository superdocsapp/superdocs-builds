"""Generate the one-page architecture diagram as SVG (A4 portrait, 794x1123 at 96dpi)."""
import io, os

W, H = 794, 1123
M = 34
CW = W - 2 * M
X0, X1 = M, W - M

INK = "#1a1a1e"
MUTED = "#6d6d78"
FAINT = "#9a9aa4"
RULE = "#d7d3ca"
PAPER = "#ffffff"

CORE_FILL = "#f6f3ec"
CORE_LINE = "#8a6a44"
CORE_INK = "#5f4526"

SD_FILL = "#eef3f8"
SD_LINE = "#3d6d9e"
SD_INK = "#2b537a"

GATE_FILL = "#fdf4e6"
GATE_LINE = "#b8801f"
GATE_INK = "#8a5f13"

HOST_FILL = "#f4f4f6"
HOST_LINE = "#b9b9c2"

OK_FILL = "#eef6ef"
OK_LINE = "#5a9163"
OK_INK = "#3f6d47"

RED_INK = "#a5563f"

SANS = "'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'SF Mono', Menlo, Consolas, monospace"

out = []
def add(s): out.append(s)

def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def text(x, y, s, size=11, fill=INK, weight="400", anchor="start", family=SANS, spacing=None):
    ls = f' letter-spacing="{spacing}"' if spacing else ""
    add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{ls}>{esc(s)}</text>')

def box(x, y, w, h, fill=PAPER, stroke=RULE, sw=1, r=7, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

def arrow(x1, y1, x2, y2, stroke=MUTED, sw=1.6, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" '
        f'stroke-width="{sw}" marker-end="url(#tip)"{d}/>')

def line(x1, y1, x2, y2, stroke=RULE, sw=1, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" '
        f'stroke-width="{sw}"{d}/>')

def chip(x, y, w, h, label, sub=None, fill=PAPER, stroke=RULE, ink=INK, size=10.5):
    box(x, y, w, h, fill=fill, stroke=stroke, r=5)
    if sub:
        text(x + w / 2, y + h / 2 - 3, label, size=size, fill=ink, weight="600", anchor="middle")
        text(x + w / 2, y + h / 2 + 11, sub, size=8.6, fill=MUTED, anchor="middle")
    else:
        text(x + w / 2, y + h / 2 + 3.6, label, size=size, fill=ink, weight="600", anchor="middle")

add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
add(f'''<defs>
<marker id="tip" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
  <path d="M 0 1 L 9 5 L 0 9 z" fill="{MUTED}"/>
</marker>
</defs>''')
add(f'<rect width="{W}" height="{H}" fill="{PAPER}"/>')

# ---------------------------------------------------------------- title
y = 54
text(X0, y, "Manuscript Compiler for Obsidian", size=24, weight="700")
text(X1, y - 13, "Elizabeth Sobiya", size=9.5, fill=MUTED, anchor="end")
text(X1, y, "SuperDocs Round 2 · assigned build", size=9.5, fill=FAINT, anchor="end")
y += 18
text(X0, y, "An Obsidian vault becomes a print-ready book. Typesetting is deterministic and free; "
            "SuperDocs renders and edits.", size=10.5, fill=MUTED)
y += 13
line(X0, y, X1, y, stroke=INK, sw=1.4)

# ---------------------------------------------------------------- hosts
y += 24
HOST_H = 62
hw = (CW - 20) / 2
for i, (title, path, sub) in enumerate([
        ("Obsidian plugin", "src/main.ts", "commands · report view · review modal · spend dialog"),
        ("Headless CLI", "src/cli/index.ts", "compile · check · roundtrip · status")]):
    bx = X0 + i * (hw + 20)
    box(bx, y, hw, HOST_H, fill=HOST_FILL, stroke=HOST_LINE)
    text(bx + 13, y + 22, title, size=12, weight="700")
    text(bx + 13, y + 37, path, size=8.8, fill=MUTED, family=MONO)
    text(bx + 13, y + 51, sub, size=8.6, fill=MUTED)

# ---------------------------------------------------------------- seam
y += HOST_H
seam_y = y + 20
line(X0, seam_y, X1, seam_y, stroke=CORE_LINE, sw=1.1, dash="5 4")
add(f'<rect x="{X0 + 88}" y="{seam_y - 9}" width="{CW - 176}" height="18" fill="{PAPER}"/>')
text(W / 2, seam_y + 3.5, "VaultReader  +  Transport   —   injected, never imported",
     size=9.8, fill=CORE_INK, weight="600", anchor="middle")
text(W / 2, seam_y + 20, "the seam that lets 131 tests run with no vault, no Obsidian, no network and no API key",
     size=8.6, fill=MUTED, anchor="middle")

# ---------------------------------------------------------------- sources
y = seam_y + 34
VAULT_H = 82
box(X0, y, CW, VAULT_H)
text(X0 + 13, y + 18, "THE VAULT", size=8.4, fill=FAINT, weight="700", spacing="1.1")
cw = (CW - 26 - 3 * 9) / 4
for i, (lab, sub) in enumerate([
        ("Spine note", "order · parts · metadata"),
        ("Chapter notes", "markdown, as written"),
        ("Figures", "png · jpg · svg"),
        ("Bibliography", "BibTeX .bib")]):
    chip(X0 + 13 + i * (cw + 9), y + 26, cw, 42, lab, sub=sub, size=9.6)

y += VAULT_H
arrow(W / 2, y + 4, W / 2, y + 22)

# ---------------------------------------------------------------- core
core_top = y + 26
CORE_H = 302
box(X0, core_top, CW, CORE_H, fill=CORE_FILL, stroke=CORE_LINE, sw=1.4)
text(X0 + 15, core_top + 23, "src/core", size=13, weight="700", fill=CORE_INK, family=MONO)
text(X0 + 96, core_top + 23, "pure  ·  offline  ·  deterministic  ·  no network, ever", size=9.8, fill=CORE_INK)
text(X1 - 15, core_top + 23, "0 operations", size=10.2, fill=OK_INK, weight="700", anchor="end")

sy = core_top + 40
sw_ = (CW - 30 - 3 * 10) / 4
CHIP_H, ROW_GAP = 46, 66
stages = [
    ("parse spine", "order, parts, options"),
    ("read .bib", "entries → map"),
    ("hash sources", "note + transclusions"),
    ("plan reuse", "what can be skipped"),
    ("render", "markdown → tokens"),
    ("rehydrate", "reused chapters"),
    ("number", "one pass, whole book"),
    ("assemble", "matter + parts + notes"),
]
for i, (lab, sub) in enumerate(stages):
    r, c = divmod(i, 4)
    cx = X0 + 15 + c * (sw_ + 10)
    cy = sy + r * ROW_GAP
    chip(cx, cy, sw_, CHIP_H, lab, sub=sub, fill=PAPER, stroke=CORE_LINE, ink=CORE_INK, size=10.2)
    if c < 3:
        arrow(cx + sw_ + 1, cy + CHIP_H / 2, cx + sw_ + 9, cy + CHIP_H / 2, stroke=CORE_LINE, sw=1.3)

# wrap connector: end of row one, down and back to the start of row two
_rx = X0 + 15 + 3 * (sw_ + 10) + sw_ / 2
_lx = X0 + 15 + sw_ / 2
_ym = sy + CHIP_H + 10
line(_rx, sy + CHIP_H + 1, _rx, _ym, stroke=CORE_LINE, sw=1.2)
line(_rx, _ym, _lx, _ym, stroke=CORE_LINE, sw=1.2, dash="3 3")
arrow(_lx, _ym, _lx, sy + ROW_GAP - 1, stroke=CORE_LINE, sw=1.2)

# the token idea
ty = sy + ROW_GAP + CHIP_H + 16
box(X0 + 15, ty, CW - 30, 42, fill=PAPER, stroke=CORE_LINE, r=5)
text(X0 + 26, ty + 18, "Why tokens:", size=9.8, weight="700", fill=CORE_INK)
text(X0 + 92, ty + 18, "a chapter renders once to HTML that still says", size=9.5, fill=INK)
text(X0 + 326, ty + 18, "⟨fig:north-sheet-4⟩", size=9.2, fill=CORE_INK, family=MONO)
text(X0 + 448, ty + 18, "where “Figure 1.1” belongs.", size=9.5, fill=INK)
text(X0 + 26, ty + 33, "Numbers are assigned once, at assembly, so a chapter's bytes depend on that chapter alone "
                       "— never on its neighbours.", size=9.2, fill=MUTED)

# manifest
my = ty + 54
box(X0 + 15, my, CW - 30, 76, fill=PAPER, stroke=CORE_LINE, r=5)
text(X0 + 26, my + 18, ".manuscript-cache/manifest.json", size=9.4, weight="700", fill=CORE_INK, family=MONO)
text(X0 + 222, my + 18, "per-chapter hashes · cached tokenised HTML · figure URLs · resume point", size=8.8, fill=MUTED)
vw = (CW - 52 - 3 * 9) / 4
for i, (lab, col) in enumerate([
        ("unchanged", OK_INK), ("renumbered", CORE_INK), ("rewritten", RED_INK), ("added / removed", MUTED)]):
    vx = X0 + 26 + i * (vw + 9)
    box(vx, my + 27, vw, 22, fill=PAPER, stroke=RULE, r=4)
    text(vx + vw / 2, my + 41.5, lab, size=8.8, fill=col, weight="600", anchor="middle")
text(X0 + 26, my + 66, "every chapter gets exactly one verdict per compile, and the compiler can prove each",
     size=8.4, fill=FAINT)

y = core_top + CORE_H
arrow(W / 2, y + 4, W / 2, y + 22)

# ---------------------------------------------------------------- assembled html
y += 26
ASM_H = 54
box(X0, y, CW, ASM_H, fill=PAPER, stroke=INK, sw=1.3)
text(X0 + 15, y + 22, "Assembled manuscript HTML", size=12, weight="700")
text(X0 + 15, y + 38, "real page breaks · footnotes as out-of-flow parts · hosted figure URLs · "
                      "anchors for the contents and every cross-reference", size=8.8, fill=MUTED)

y += ASM_H
bw1 = (CW - 18) * 0.40
bx2 = X0 + bw1 + 18
bw2 = CW - bw1 - 18
arrow(X0 + bw1 / 2, y + 3, X0 + bw1 / 2, y + 21)
arrow(bx2 + bw2 / 2, y + 3, bx2 + bw2 / 2, y + 21)

y += 25
BR_H = 88
box(X0, y, bw1, BR_H, fill=OK_FILL, stroke=OK_LINE)
text(X0 + 13, y + 22, "Offline output", size=12, weight="700", fill=OK_INK)
text(X0 + 13, y + 40, "Self-contained HTML proof", size=9.4, fill=INK)
text(X0 + 13, y + 55, "No key. No network. No cost.", size=9.4, fill=MUTED)
text(X0 + 13, y + 75, "0 operations", size=10.4, weight="700", fill=OK_INK)

box(bx2, y, bw2, BR_H, fill=SD_FILL, stroke=SD_LINE)
text(bx2 + 13, y + 22, "src/superdocs  →  api.superdocs.app", size=12, weight="700", fill=SD_INK)
text(bx2 + 13, y + 40, "images/upload-base64", size=8.9, fill=INK, family=MONO)
text(bx2 + 160, y + 40, "content-addressed, uploaded once", size=8.9, fill=MUTED)
text(bx2 + 13, y + 55, "documents/export", size=8.9, fill=INK, family=MONO)
text(bx2 + 160, y + 55, "PDF  +  DOCX, page breaks and footnotes intact", size=8.9, fill=MUTED)
text(bx2 + 13, y + 75, "0 operations — exports and image uploads are not billable", size=9.4, weight="700", fill=SD_INK)

y += BR_H
arrow(W / 2, y + 3, W / 2, y + 21)

# ---------------------------------------------------------------- editorial + gate
y += 25
GATE_H = 108
box(X0, y, CW, GATE_H, fill=GATE_FILL, stroke=GATE_LINE, sw=1.3)
text(X0 + 15, y + 22, "Editorial passes — the only place this spends money", size=12, weight="700", fill=GATE_INK)
text(X1 - 15, y + 22, "1 operation each", size=10.2, weight="700", fill=GATE_INK, anchor="end")

gy = y + 34
gw = (CW - 30 - 3 * 24) / 4
for i, (lab, sub) in enumerate([
        ("cost preview", "scope + price, before"),
        ("chat", "ask_every_time"),
        ("HUMAN GATE", "accept / reject each"),
        ("approve", "decisions respected")]):
    gx = X0 + 15 + i * (gw + 24)
    is_gate = lab == "HUMAN GATE"
    chip(gx, gy, gw, 42, lab, sub=sub, fill=PAPER,
         stroke=GATE_LINE if is_gate else RULE,
         ink=GATE_INK if is_gate else INK, size=10.4 if is_gate else 10)
    if i < 3:
        arrow(gx + gw + 2, gy + 21, gx + gw + 21, gy + 21, stroke=GATE_LINE, sw=1.3)
text(X0 + 15, y + GATE_H - 20, "The manuscript is data, not instructions: content travels inside a stated boundary and",
     size=8.6, fill=GATE_INK)
text(X0 + 15, y + GATE_H - 8, "suspicious lines are reported with file and line. Nothing reaches the vault without an explicit decision.",
     size=8.6, fill=GATE_INK)

# ---------------------------------------------------------------- decisions
y += GATE_H + 20
text(X0, y, "THREE DECISIONS THAT SHAPED IT", size=8.4, fill=FAINT, weight="700", spacing="1.1")
y += 15
decisions = [
    ("No model in the compile path.", "Order, numbering and citations have one right answer. A model makes them dearer and non-repeatable."),
    ("Numbers assigned at assembly.", "Costs one extra pass; buys a recompile that can name exactly which chapters moved, and prove it."),
    ("Ids keyed off paths, not position.", "Costs uglier ids; buys reordering a book that re-renders nothing at all."),
]
for head, body in decisions:
    text(X0, y, head, size=9.4, weight="700", fill=INK)
    text(X0 + 168, y, body, size=9.0, fill=MUTED)
    y += 15

# ---------------------------------------------------------------- footer metrics
y += 8
line(X0, y, X1, y, stroke=INK, sw=1.2)
y += 19
text(X0, y, "MEASURED", size=8.4, fill=FAINT, weight="700", spacing="1.1")
metrics = [
    ("458 ms", "60 chapters · 90k words"),
    ("10 of 11", "untouched, byte-identical"),
    ("0", "re-rendered on reorder"),
    ("131", "tests, no key needed"),
    ("4 / 500", "ops, whole project"),
]
mw = (CW - 80) / len(metrics)
for i, (big, small) in enumerate(metrics):
    mx = X0 + 80 + i * mw
    text(mx, y, big, size=13.5, weight="700", fill=INK)
    text(mx, y + 13, small, size=8.3, fill=MUTED)
y += 13

print("content ends at y =", round(y), "of", H)
assert y < H - 10, f"content overflows the page: {y} >= {H - 10}"
add("</svg>")

dest = os.path.join(os.path.dirname(os.path.abspath(__file__)), "architecture-diagram.svg")
os.makedirs(os.path.dirname(dest), exist_ok=True)
tmp = dest + ".tmp"
io.open(tmp, "w", encoding="utf-8").write("\n".join(out) + "\n")
os.replace(tmp, dest)
print("wrote", dest)
