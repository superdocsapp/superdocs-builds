"""Generate the one-page write-up as SVG (A4 portrait), matching the diagram's design."""
import base64, io, os, re

W, H = 794, 1123
M = 42
CW = W - 2 * M
X0, X1 = M, W - M

INK = "#1a1a1e"
MUTED = "#54545e"
FAINT = "#9a9aa4"
RULE = "#d7d3ca"
PAPER = "#ffffff"
CORE_INK = "#5f4526"
CORE_LINE = "#8a6a44"
OK_INK = "#3f6d47"
BAND = "#f6f3ec"

SANS = "'Helvetica Neue', Helvetica, Arial, sans-serif"

out = []
def add(s): out.append(s)

def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ---------------------------------------------------------------- text metrics
NARROW = set("iljtfrI.,;:'!|()[]-`")
WIDE = set("mwMW@%")


def run_width(s, size, bold=False):
    """Estimate rendered width. Deliberately a little generous so lines never overflow."""
    w = 0.0
    for ch in s:
        if ch == " ":
            w += 0.278
        elif ch in NARROW:
            w += 0.30
        elif ch in WIDE:
            w += 0.86
        elif ch.isupper() or ch.isdigit():
            w += 0.62
        else:
            w += 0.535
    if bold:
        w *= 1.045
    return w * size * 1.02


TOKEN_RE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*)")


def parse_runs(text):
    """'plain **bold** more' -> [(text, style)] where style is '', 'b' or 'i'."""
    runs = []
    for part in TOKEN_RE.split(text):
        if not part:
            continue
        if part.startswith("**"):
            runs.append((part[2:-2], "b"))
        elif part.startswith("*"):
            runs.append((part[1:-1], "i"))
        else:
            runs.append((part, ""))
    return runs


def wrap_runs(runs, size, max_w):
    """Greedy word wrap that keeps run styles. Returns a list of lines of runs."""
    lines, cur, cur_w = [], [], 0.0
    for txt, style in runs:
        for i, word in enumerate(re.split(r"(\s+)", txt)):
            if word == "":
                continue
            ww = run_width(word, size, style == "b")
            if word.isspace():
                if cur:
                    cur.append((word, style))
                    cur_w += ww
                continue
            # A run of pure punctuation belongs to the word before it. Without this,
            # "**bold**, then" breaks after the bold and the comma starts a new line.
            sticky = cur and all(c in ",.;:!?)]}\u2019\u201d%" for c in word)
            if cur_w + ww > max_w and cur and not sticky:
                while cur and cur[-1][0].isspace():
                    cur.pop()
                lines.append(cur)
                cur, cur_w = [], 0.0
            cur.append((word, style))
            cur_w += ww
    if cur:
        while cur and cur[-1][0].isspace():
            cur.pop()
        lines.append(cur)
    return lines


def emit_line(x, y, line, size, fill):
    # Merge neighbouring tokens that share a style into one tspan, so the renderer
    # kerns each phrase as a phrase rather than as a string of fragments.
    merged = []
    for txt, style in line:
        if merged and merged[-1][1] == style:
            merged[-1][0] += txt
        else:
            merged.append([txt, style])
    parts = []
    for txt, style in merged:
        t = esc(txt).replace(" ", "&#160;")
        if style == "b":
            parts.append(f'<tspan font-weight="700" fill="{INK}">{t}</tspan>')
        elif style == "i":
            parts.append(f'<tspan font-style="italic">{t}</tspan>')
        else:
            parts.append(f"<tspan>{t}</tspan>")
    add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{SANS}" font-size="{size}" '
        f'fill="{fill}" xml:space="preserve">{"".join(parts)}</text>')


def paragraph(x, y, text, size=11.0, lh=16.2, fill=MUTED, width=None):
    width = width or CW
    lines = wrap_runs(parse_runs(text), size, width)
    for ln in lines:
        emit_line(x, y, ln, size, fill)
        y += lh
    return y


def text(x, y, s, size=11, fill=INK, weight="400", anchor="start", spacing=None, style=""):
    ls = f' letter-spacing="{spacing}"' if spacing else ""
    st = ' font-style="italic"' if style == "i" else ""
    add(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{SANS}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{ls}{st}>{esc(s)}</text>')


def line(x1, y1, x2, y2, stroke=RULE, sw=1):
    add(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{sw}"/>')


def heading(y, s):
    y += 8
    text(X0, y, s, size=13, weight="700", fill=INK)
    return y + 16


add(f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
add(f'<rect width="{W}" height="{H}" fill="{PAPER}"/>')

# ---------------------------------------------------------------- header
y = 62
text(X0, y, "Manuscript Compiler for Obsidian", size=25, weight="700")
y += 22
y = paragraph(X0, y, "**An Obsidian vault becomes a print-ready book — and the typesetting is done "
                     "without a language model.**", size=11.6, lh=16, fill=INK)
y += 3
text(X0, y, "Elizabeth Sobiya   ·   built on SuperDocs   ·   Round 2, assigned build", size=9.6, fill=FAINT)
y += 10
line(X0, y, X1, y, stroke=INK, sw=1.4)

# ---------------------------------------------------------------- results
y += 22
text(X0, y, "RESULTS, MEASURED", size=9, weight="700", fill=FAINT, spacing="1.2")
y += 12

rows = [
    ("458 ms", "to compile 60 chapters — ~90,000 words, ~300 printed pages, 120 figures, 180 footnotes "
               "— with numbering continuous and correct across every chapter boundary"),
    ("10 of 11", "chapters come through **byte-identical** after editing the eleventh. Reordering the "
                 "book re-renders **zero**"),
    ("131 tests", "pass on a fresh clone with no API key, no network, no vault and no Obsidian"),
    ("20 · 6 · 7", "real Word page breaks, real Word footnotes and embedded images, verified inside the "
                   "exported .docx"),
    ("4 of 500", "SuperDocs operations for the entire project, including every live export and two full "
                 "four-call round trips. **Compiling costs zero. Exporting costs zero.**"),
]
band_top = y
NUMCOL = 104
row_ys = []
yy = y + 14
for big, body in rows:
    row_ys.append(yy)
    text(X0 + 12, yy + 1, big, size=13.5, weight="700", fill=CORE_INK)
    end = paragraph(X0 + NUMCOL, yy, body, size=10.2, lh=14.2, fill=MUTED, width=CW - NUMCOL - 14)
    yy = max(end, yy + 20) + 6
band_h = yy - band_top - 2
add(f'<rect x="{X0}" y="{band_top}" width="{CW}" height="{band_h:.1f}" rx="7" fill="{BAND}" stroke="{CORE_LINE}" stroke-width="1"/>')
# redraw the band contents above the fill
for (big, body), ry in zip(rows, row_ys):
    text(X0 + 12, ry + 1, big, size=13.5, weight="700", fill=CORE_INK)
    paragraph(X0 + NUMCOL, ry, body, size=10.2, lh=14.2, fill=MUTED, width=CW - NUMCOL - 14)
y = band_top + band_h

# ---------------------------------------------------------------- who
y = heading(y + 6, "What it is, and who it is for")
y = paragraph(X0, y, "An author, a thesis writer or a documentation lead keeps a book as a few hundred "
                     "notes. They can search it, link it and think in it — but they cannot *hand it to "
                     "anyone*, because a vault is not a manuscript.")
y += 8
y = paragraph(X0, y, "This closes that gap. One index note, the **spine**, lists the chapters in order. "
                     "Compiling turns the vault into a real long-form document: chapters in order, heading "
                     "levels normalised, front and back matter generated, inline notes converted to numbered "
                     "footnotes, figures captioned and numbered continuously, citations resolved against a "
                     "BibTeX file, and a table of contents built. Out come a print-ready **PDF** and a "
                     "**DOCX an editor can mark up**, rendered by SuperDocs. It ships as an Obsidian plugin "
                     "and as a headless CLI over the same compiler, so a book kept in git compiles in CI "
                     "exactly as it does in the app.")

# ---------------------------------------------------------------- trade-offs
y = heading(y + 6, "The trade-off that decides everything")
y = paragraph(X0, y, "**Typesetting is not a job for a language model.** Chapter order, figure numbering, "
                     "footnote numbering, citation resolution and heading normalisation are deterministic "
                     "problems with one right answer. Handing them to a model makes them slower, dearer, and "
                     "— worst — *non-repeatable*: compile twice, get two books.")
y += 8
y = paragraph(X0, y, "So the compiler is pure, local, offline and free. SuperDocs does the two things it is "
                     "genuinely better at: rendering a real Word and PDF file, and running **optional "
                     "editorial passes** — draft a preface, write a jacket blurb, report whether chapter "
                     "nine's voice has drifted. Each is opt-in, scoped to a slice rather than 300 pages, "
                     "priced before it runs, and reviewed change by change. The cost of this split is that "
                     "the interesting AI work sits at the edges rather than the centre. What it buys is an "
                     "author who can recompile fifty times in an afternoon for nothing, and get the same "
                     "book every time.")
y += 8
y = paragraph(X0, y, "**Two smaller trade-offs, made the same way.** Numbers are assigned at *assembly*, not "
                     "at render, so a chapter's bytes depend on that chapter alone — one extra pass, in "
                     "exchange for a recompile that can name exactly which chapters moved, and prove it. And "
                     "every id is keyed off a note's *path* rather than its position, which yields uglier ids "
                     "and reordering that re-renders nothing at all.")

# ---------------------------------------------------------------- limits
y = heading(y + 6, "What it will not do")
y = paragraph(X0, y, "It never invents anything. An unresolved citation prints a visible marker and fails the "
                     "compile; a cross-reference to a figure no chapter places is left visible rather than "
                     "given a plausible number; a missing figure is named, not skipped. A success message only "
                     "ever means the file is on disk with bytes in it.")
y += 8
y = paragraph(X0, y, "Honest gaps: the table of contents has **no page numbers** — pagination does not exist "
                     "until the renderer lays the book out, and a fabricated number is worse than none. "
                     "Footnotes land at the page foot in DOCX but are collected as endnotes in PDF; that is "
                     "the export pipeline's behaviour, and it is reported as a bug. The prompt-injection "
                     "scanner is a tripwire, not a classifier — the real protection is that no model-proposed "
                     "change reaches the vault without a human approving it, item by item.")

def _thumb(fname):
    """
    Downscaled copies of the committed PDF-page renders.

    They are embedded as base64 inside the SVG, so full-resolution originals would
    push the file past half a megabyte for pictures printed 40mm wide. Regenerate
    with:  sips -Z 420 -s format png --out docs/images/thumb-X.png docs/images/X.png
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "images", "thumb-" + fname)


# ---------------------------------------------------------------- evidence
# Real pages from the compiled demo book, embedded so the page carries its own proof.
y = heading(y + 6, "The output, unretouched")
THUMBS = [
    (_thumb("pdf-title-page.png"), "Title page, generated from the spine's frontmatter"),
    (_thumb("pdf-contents.png"), "Contents — clickable, indented, no faked page numbers"),
    (_thumb("pdf-chapter-with-figure.png"), "A chapter: numbered figure, footnotes, live citation"),
]
# Size the row to whatever vertical space is actually left, so the page always
# holds exactly one page and the strip never pushes the footer off it.
FOOTER_RESERVE = 62
CAPTION_RESERVE = 26
avail = (H - 24) - y - CAPTION_RESERVE - FOOTER_RESERVE
th = max(90.0, min(avail, 190.0))
tw = th * 794 / 1123
gap = 13
row_w = 3 * tw + 2 * gap
x_start = X0
for i, (path, cap) in enumerate(THUMBS):
    b64 = base64.b64encode(io.open(path, "rb").read()).decode()
    tx = x_start + i * (tw + gap)
    add(f'<image x="{tx:.1f}" y="{y:.1f}" width="{tw:.1f}" height="{th:.1f}" '
        f'preserveAspectRatio="xMidYMid meet" xlink:href="data:image/png;base64,{b64}" '
        f'href="data:image/png;base64,{b64}"/>')
    add(f'<rect x="{tx:.1f}" y="{y:.1f}" width="{tw:.1f}" height="{th:.1f}" fill="none" '
        f'stroke="{RULE}" stroke-width="1"/>')
    for j, ln in enumerate(wrap_runs(parse_runs(cap), 8.0, tw + gap - 4)):
        emit_line(tx, y + th + 11 + j * 9.8, ln, 8.0, FAINT)

# The thumbnails leave room to their right; spend it on what is actually in those
# files, which is the part a reader cannot see from a picture.
fx = x_start + row_w + 26
fw = X1 - fx
ey = y + 12
ey = paragraph(fx, ey, "Every page here is output from **npm run demo:export**, "
                       "unedited.", size=9.4, lh=13, fill=MUTED, width=fw)
ey += 8
for fact in [
        "**25-page PDF** · 24 bookmarks · 36 working hyperlinks",
        "**48 KB DOCX** · 20 real Word page breaks · 6 real Word footnotes · 7 embedded images",
        "**0 operations** for all of it — the compiler writes the markup itself rather than asking a model to",
]:
    ey = paragraph(fx, ey, "· " + fact, size=9.4, lh=13, fill=MUTED, width=fw)
    ey += 6

y += th + CAPTION_RESERVE

# ---------------------------------------------------------------- footer
y += 6
line(X0, y, X1, y, stroke=RULE, sw=1)
y += 13
y = paragraph(X0, y, "Verified by: npm run verify (131 tests) · test/scale.test.ts (the 300-page fixture) · "
                     "node dist/cli.mjs roundtrip demo-vault, against the live API. The demo manuscript, its "
                     "author, its publisher and every source in its bibliography are fictional.",
              size=8.8, lh=12, fill=FAINT)

print("content ends at y =", round(y), "of", H)
assert y < H - 20, f"overflows: {y}"
add("</svg>")

dest = os.path.join(os.path.dirname(os.path.abspath(__file__)), "one-page-writeup.svg")
tmp = dest + ".tmp"
io.open(tmp, "w", encoding="utf-8").write("\n".join(out) + "\n")
os.replace(tmp, dest)
print("wrote", dest)
