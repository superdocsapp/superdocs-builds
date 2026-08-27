"""The recovery floor: get the document back, every time, with its pictures.

This is the part that must never need a network, never need a key, and never
raise. It reads the parts out of the container by hand (`salvage`), repairs the
body XML far enough to parse (`salvage.repair_xml`), reads structure out of it
(`docx.read_blocks`), puts the recovered pictures back where the relationships
say they were (`media`), and writes a clean package (`docx.write_docx`).

Why the pictures are not an extra
---------------------------------
A `.docx` stores its images as ordinary ZIP members, entirely separate from
`word/document.xml`. They survive exactly the damage that destroys the index, so
a rebuild that drops them is throwing away bytes that were sitting right there.
From the research, on what a recovery actually cost somebody: *"the photos I got
off my phone again — the ones I still had."* The words came back and the
pictures did not, and re-sourcing the pictures was most of the work.

Stdlib only
-----------
Nothing here imports `lxml` or `python-docx` at module scope. The floor's whole
promise is that it runs offline, in milliseconds, for somebody already having a
bad day, and a floor that cannot import is not a floor. `lxml` is used when it
is installed, as one extra tier of tolerance between a strict parse and a
run-by-run regex, and its absence costs only that tier.

The honesty is in the verdict, not the wording. A structural parse that lost
nothing is "full"; a run-by-run rescue, or a rebuild that could not carry every
picture, is "partial"; nothing recovered at all is "refused". The CLI and the
honesty tests assert against these exact tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from . import docx, media, salvage
from .salvage import plural

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

DOCUMENT_PART = "word/document.xml"
DOC_RELS_PART = "word/_rels/document.xml.rels"

#: Parts that carry a person's words but are not the body of the document.
ASIDE_PARTS = (
    "word/footnotes.xml",
    "word/endnotes.xml",
    "word/header",
    "word/footer",
)

#: Literal marker the recovered asides are set down behind. A person opening the
#: rebuild sees exactly where their footnotes and headers ended up, instead of
#: them being silently folded into the body and changing what the document says.
ASIDES_MARKER = "--- RECOVERED ASIDES ---"

#: The heading the unplaceable pictures go under.
PICTURES_HEADING = "Pictures recovered from this document"

Progress = object  # (stage, message) -> None


@dataclass
class Result:
    """The one shape the floor produces.

    The verdict is the honest token the harness asserts on. ``output`` is the
    rebuilt ``.docx`` bytes; ``output_path`` is where they were written. The
    picture fields exist because "we got your document back" and "we got your
    document back without its photographs" must not look the same to the person
    reading the report.
    """

    verdict: str = "refused"          # full | partial | refused
    word_count: int = 0
    output_path: str = "local_rebuild.docx"
    method: str = "empty"             # xml | regex | empty
    asides_text: str = ""
    ok: bool = False
    output: bytes = b""
    lost: list[str] = field(default_factory=list)
    structure_preserved: bool = False

    #: The rebuilt document itself, with its pictures inline, so somebody can
    #: look before deciding whether the recovery was worth anything. From the
    #: research, on a paid repair tool: "It just said 'repair successful'. I
    #: didn't know if it had actually got anything."
    preview_html: str = ""
    images_recovered: int = 0         # written into the rebuilt file
    images_unplaced: int = 0          # recovered, but set at the end
    images_lost: list[str] = field(default_factory=list)
    tables_recovered: int = 0
    headings_recovered: int = 0

    def as_payload(self, download: str | None = None,
                   style: str | None = None) -> dict:
        """The manifest the page is handed, built here rather than at the door.

        The interface fixtures are captured through this same method, so a
        fixture cannot describe a payload the engine never produces — which is
        exactly how the page and the engine drifted apart while both of their
        test suites stayed green.
        """
        return {
            "ok": self.ok,
            "verdict": self.verdict,
            "word_count": self.word_count,
            "method": self.method,
            "asides_text": self.asides_text,
            "output_path": self.output_path,
            "lost": self.lost,
            "preview_html": self.preview_html,
            "structure_preserved": self.structure_preserved,
            "images_recovered": self.images_recovered,
            "images_unplaced": self.images_unplaced,
            "images_lost": self.images_lost,
            "tables_recovered": self.tables_recovered,
            "download": download,
            "style": style,
            # Filled in by the styling pass. Present on every payload so a
            # consumer never has to ask whether the key exists before reading
            # it -- including on a refusal, where the answer is simply no.
            "styled": False,
            "styling_note": "",
            "styling_rejected": False,
            "plain_download": download,
        }


# -- reading -----------------------------------------------------------------

def _read_targets(members: dict[str, bytes]) -> tuple[dict[str, str], dict[str, str]]:
    """The body's relationship map, and where the other pictures came from.

    Two separate questions, deliberately not merged into one dictionary:

    * **Which file does this body reference point at?** Only the body's own map
      can answer that. A header's `rId4` and the body's `rId4` are unrelated
      numbers that happen to collide, so folding the header's map into the
      body's would place the wrong picture in the wrong paragraph — the exact
      failure `media`'s docstring says it refuses to risk.
    * **Where did this picture come from?** Answerable for a header or footer
      logo, whose relationship lives in `word/_rels/header1.xml.rels`. Reading
      only the body's map left those in the "we could not work out where this
      went" pile when their origin was in the file, readable, all along.

    So: the first return value places pictures, the second only describes them.
    """
    targets = media.relationship_targets(members.get(DOC_RELS_PART))
    origins: dict[str, str] = {}
    for name, blob in members.items():
        if not name.startswith("word/_rels/") or name == DOC_RELS_PART:
            continue
        part = name[len("word/_rels/"):].removesuffix(".xml.rels")
        if part.startswith("header"):
            where = "the page header"
        elif part.startswith("footer"):
            where = "the page footer"
        else:
            continue
        for target in media.relationship_targets(blob).values():
            if not media.is_external(target):
                origins.setdefault(target, where)
    return targets, origins


def _aside_name(name: str) -> bool:
    if name in ("word/footnotes.xml", "word/endnotes.xml"):
        return True
    return name.startswith("word/header") or name.startswith("word/footer")


def _recovered_xml(raw: bytes) -> bytes | None:
    """A re-serialised parse of XML too damaged for a strict reader.

    Optional tier: `lxml`'s recovering parser salvages structure that
    `salvage.repair_xml` cannot, which is the difference between keeping
    somebody's tables and handing back a wall of paragraphs. When `lxml` is not
    installed this returns None and the caller falls through to the regex, so
    the floor still stands.
    """
    try:
        import lxml.etree as LXML
    except ImportError:
        return None
    try:
        tree = LXML.fromstring(raw, LXML.XMLParser(recover=True))
    except Exception:
        return None
    if tree is None:
        return None
    try:
        return LXML.tostring(tree)
    except Exception:
        return None


def _read_body(fixed: bytes, targets: dict[str, str],
               pictures: dict[str, media.Image],
               res: Result, say) -> list[docx.Block]:
    """Structure if it can be read, text if it cannot, and say which."""
    for candidate in (fixed, _recovered_xml(fixed)):
        if candidate is None:
            continue
        try:
            blocks = docx.read_blocks(candidate, targets, pictures)
        except (ET.ParseError, ValueError):
            continue
        res.method = "xml"
        res.structure_preserved = True
        return blocks

    say("Repairing XML", "The structure would not parse; recovering the text run by run…")
    res.method = "regex"
    res.structure_preserved = False
    res.lost.append(
        "the document structure was unreadable, so headings, tables and "
        "formatting could not be preserved — only the text was recovered"
    )
    return [docx.Block("paragraph", t) for t in salvage.text_runs(fixed) if t.strip()]


def _place_pictures(blocks: list[docx.Block], pictures: dict[str, media.Image],
                    origins: dict[str, str], res: Result, say) -> None:
    """Set at the end the pictures the body could not be shown to reference.

    Either the part naming which file each reference points at did not survive,
    or the text fell back to a run-by-run read that carries no positions. They
    are still the owner's pictures, so they go at the end under a heading that
    says so — an image silently placed in the wrong paragraph is worse than one
    obviously placed last.
    """
    placed = {b.image.name for b in docx.image_blocks(blocks)}
    unplaced = [img for name, img in sorted(pictures.items()) if name not in placed]
    if not unplaced:
        return
    res.images_unplaced = len(unplaced)
    say("Reading Body", f"Recovered {plural(len(unplaced), 'picture')} whose "
                        "original position could not be worked out.")
    blocks.append(docx.Block("heading", PICTURES_HEADING, level=1))
    for img in unplaced:
        where = origins.get(img.name)
        if where:
            # Knowable, and so said. A rebuild cannot put a logo back into the
            # page header, but "this came from the page header" is a true
            # sentence and "we do not know where this went" is not.
            blocks.append(docx.Block(
                "paragraph", f"This picture was in {where} of your document."))
        blocks.append(docx.Block("image", text=img.name, image=img))


#: Every way a body part names a picture it wants: DrawingML's `r:embed` and
#: `r:link`, and VML's `r:id` for the older documents that still use it. Read
#: with a regex rather than off the parse tree so the count is available even
#: when the structure was too damaged to parse — which is exactly the case where
#: a picture is most likely to have gone missing.
_REFERENCE_RE = re.compile(
    rb'r:(?:embed|link|id)="([^"]+)"')


def _referenced_ids(xml: bytes) -> set[str]:
    return {m.group(1).decode("utf-8", "replace")
            for m in _REFERENCE_RE.finditer(xml)}


def _report_missing(xml: bytes, targets: dict[str, str],
                    pictures: dict[str, media.Image], res: Result) -> int:
    """Pictures the document asks for that the damage did not leave behind.

    Worth its own pass because it is the one picture loss nothing else can see.
    A photograph destroyed by a truncated download never reaches `media.collect`
    at all, so the writer has nothing to refuse and the report has nothing to
    mention — and the rebuild goes out saying "full" about a document that used
    to have a photograph in it and now does not. The body still carries the
    reference, which is the evidence that it was ever there.
    """
    missing = 0
    for rid in sorted(_referenced_ids(xml)):
        target = targets.get(rid)
        if target is None:
            # No relationship map, or not this map's id. The reference is
            # unresolvable either way, and a picture was meant to be here.
            missing += 1
            continue
        if media.is_external(target) or target in pictures:
            continue
        missing += 1
    if missing:
        res.images_lost.append(
            f"the document refers to {plural(missing, 'picture')} that "
            + ("were" if missing > 1 else "was")
            + " destroyed by the damage — the reference survived but the image "
            "data did not, so " + ("they" if missing > 1 else "it")
            + " could not be recovered"
        )
    return missing


def _report_external(targets: dict[str, str], res: Result) -> None:
    """A linked picture was never inside the file, so it was never lost from it.

    Saying "we could not recover this picture" about an image the document only
    ever pointed at would be telling somebody the damage cost them something it
    did not.
    """
    external = sorted({t[len(media.EXTERNAL):] for t in targets.values()
                       if media.is_external(t)})
    if external:
        res.images_lost.append(
            f"{plural(len(external), 'picture')} in this document "
            + ("were" if len(external) > 1 else "was")
            + " linked from somewhere else rather than stored inside the file, "
            "so " + ("they were" if len(external) > 1 else "it was")
            + " never in the file to recover"
        )


def _count_words(blocks: list[docx.Block]) -> int:
    total = 0
    for b in blocks:
        total += len(re.findall(r"[A-Za-z0-9']+", b.text))
        for row in b.rows or []:
            for cell in row:
                total += len(re.findall(r"[A-Za-z0-9']+", cell))
    return total


# -- the recovery ------------------------------------------------------------

def repair(data: bytes, filename: str = "document.docx",
           on_progress: object | None = None, *,
           out_dir: str | None = None) -> Result:
    """The whole recovery, as the deterministic sequence it actually is.

    `out_dir`, when given, is where `local_rebuild.docx` gets written instead
    of the process working directory (O3: concurrent web requests otherwise
    race on that one path). Set immediately, before anything downstream reads
    `output_path`. Default `None` keeps today's behaviour exactly, so the CLI
    and every caller that does not pass it sees no change at all.
    """
    res = Result()
    if out_dir is not None:
        res.output_path = str(Path(out_dir) / "local_rebuild.docx")

    def say(stage: str, message: str) -> None:
        if on_progress:
            on_progress(stage, message)  # type: ignore[call-arg]

    say("Scanning Headers", "Reading the parts out of the file…")
    s = salvage.salvage_members(data)
    res.lost.extend(s.unrecovered)
    if DOCUMENT_PART not in s.members:
        res.lost.append(
            "the main document part was not found inside the file, so there is "
            "no text to recover"
        )
        say("Reading Body", "No document body could be found.")
        return res

    say("Repairing XML", "Checking the document body for damage…")
    fixed, notes = salvage.repair_xml(s.members[DOCUMENT_PART])
    for note in notes:
        say("Repairing XML", note[0].upper() + note[1:] + ".")

    say("Reading Body", "Looking for pictures…")
    pictures = media.collect(s.members)
    targets, origins = _read_targets(s.members)
    _report_external(targets, res)

    blocks = _read_body(fixed, targets, pictures, res, say)
    missing = _report_missing(fixed, targets, pictures, res)

    # Asides: footnotes, endnotes, headers and footers, set down at the end.
    aside_texts = [_plain_text(s.members[n]) for n in sorted(s.members)
                   if _aside_name(n)]
    asides = "\n".join(t for t in aside_texts if t.strip())
    res.asides_text = asides

    res.word_count = _count_words(blocks)
    if res.word_count == 0 and not pictures:
        res.verdict = "refused"
        res.lost.append("no readable text was found in the document body")
        say("Reading Body", "No readable text was found.")
        return res

    _place_pictures(blocks, pictures, origins, res, say)

    if asides:
        blocks.append(docx.Block("paragraph", ""))
        blocks.append(docx.Block("paragraph", ASIDES_MARKER))
        blocks.append(docx.Block("paragraph", ""))
        blocks.append(docx.Block("paragraph", asides))

    say("Writing File", "Rebuilding a clean Word file…")
    plan = docx.plan_media(blocks)
    res.output = docx.write_docx(blocks, plan)
    res.preview_html = docx.blocks_to_html(blocks, inline_images=True)

    res.images_recovered = len(plan.carried)
    res.tables_recovered = sum(1 for b in blocks if b.kind == "table")
    res.headings_recovered = sum(1 for b in blocks if b.kind == "heading")
    for dropped in plan.dropped:
        res.images_lost.append(
            f"one picture could not be put back because {dropped.reason}")
    if any(b.from_table for b in docx.image_blocks(blocks)):
        res.lost.append(
            "a picture that was inside a table has been placed just after the "
            "table rather than in its cell, so it is in the document but not in "
            "the grid"
        )

    with open(res.output_path, "wb") as fh:
        fh.write(res.output)
    res.ok = True

    # A recovery that could not carry every picture is not a full recovery, and
    # the report must not round it up to one. This is the check the measurement
    # harness could not make and so did not: word recall alone called a rebuild
    # that had dropped every photograph in the document a complete success.
    res.verdict = ("full"
                   if res.method == "xml" and not plan.dropped and not missing
                   else "partial")

    say("Done", "The rebuilt file is ready to download.")
    return res


def _plain_text(xml: bytes) -> str:
    """All text of an aside part, as one blob, tolerant of damage."""
    try:
        root = ET.fromstring(xml)
        return " ".join(t for t in root.itertext() if t and t.strip())
    except ET.ParseError:
        return _unescape(re.sub(r"<[^>]+>", " ", xml.decode("utf-8", "replace")))


def _unescape(s: str) -> str:
    return (s.replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&"))
