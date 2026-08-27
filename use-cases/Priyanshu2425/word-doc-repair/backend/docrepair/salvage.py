"""Getting content out of a DOCX that will not open.

A DOCX is a ZIP of XML parts. It breaks in a handful of recognisable ways, and
each one needs a different move:

  * The ZIP central directory is damaged or truncated -- the file "is not a
    valid archive". Members can often still be found by scanning for local file
    headers, which is what `salvage_members` does.
  * `word/document.xml` is malformed -- an unclosed tag, a raw `&`, a stray
    control character. A strict parser refuses the whole document over one bad
    byte, so we repair the common cases and then fall back to pulling text out
    of the runs directly.
  * A part is simply missing. `[Content_Types].xml` and the relationship parts
    are rebuildable from scratch; the document body is not.

Nothing here promises a full repair. Every function reports what it could not
do, because the owner finding out later is the failure mode this tool exists to
prevent.
"""

from __future__ import annotations

import io
import re
import zipfile
import zlib
from dataclasses import dataclass, field

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# A local file header. Scanning for these recovers members when the central
# directory -- which is at the END of the file, and so is what a truncated
# download loses first -- is gone.
_LOCAL_HEADER = b"PK\x03\x04"

# Standard OOXML plumbing. These are regenerated on write, so damage to them
# costs the owner nothing and must not be reported as lost content.
REBUILDABLE = {
    "[Content_Types].xml",
    "_rels/.rels",
    "word/_rels/document.xml.rels",
    "word/styles.xml",
}

_ILLEGAL_XML = re.compile(
    rb"[\x00-\x08\x0b\x0c\x0e-\x1f]"  # control characters XML 1.0 forbids
)
# A bare ampersand: one not already starting a valid entity.
_BARE_AMP = re.compile(rb"&(?!#[0-9]+;|#x[0-9a-fA-F]+;|[a-zA-Z][a-zA-Z0-9]*;)")


def plural(n: int, noun: str, plural_form: str | None = None) -> str:
    """Consumer copy, not log output. "1 table" and "2 tables", never "1 table(s)"."""
    return f"{n} {noun}" if n == 1 else f"{n} {plural_form or noun + 's'}"


@dataclass
class Salvage:
    members: dict[str, bytes] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    unrecovered: list[str] = field(default_factory=list)

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    def lost(self, msg: str) -> None:
        self.unrecovered.append(msg)


def salvage_members(data: bytes) -> Salvage:
    """Get whatever parts can be read out of the container."""
    out = Salvage()

    # The happy path first: a readable archive.
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            try:
                bad = z.testzip()
            except zlib.error:
                # Damage *inside* a member's compressed stream. `testzip` raises
                # instead of naming it, and an uncaught raise here reached the
                # web endpoint as a 500 on a bit-rotted file -- BUG-065. The
                # name comes from the per-member reads below instead.
                bad = "?"
            failed = []
            for info in z.infolist():
                name = info.filename
                try:
                    content = z.read(info)
                except Exception:
                    failed.append(name)
                    continue
                # A name can appear twice in one archive -- CVE-2025-31672's
                # shape, and what a bad merge or a partial overwrite leaves
                # behind. `read(name)` answers with whichever copy the index
                # lists last, which may be the empty one. Keep the copy with
                # something in it: the owner's words are in the archive either
                # way, and choosing the emptier copy would lose them on a file
                # that was never really damaged.
                if len(content) >= len(out.members.get(name, b"")):
                    out.members[name] = content
            if failed:
                # The index was readable and a member was not. `read` throws
                # away everything it had already inflated when a stream goes
                # bad partway; the local-header pass keeps that prefix, which
                # on rot in the middle of a body is the difference between half
                # a document and none of it.
                _recover_by_local_headers(data, out)
                for name in failed:
                    if name not in out.members:
                        out.lost(f"one section of the file ({name}) is present "
                                 "but its data is unreadable")
            if bad:
                out.note("part of the file failed its integrity check; read what was readable")
            elif out.members and not out.unrecovered:
                out.note("the container opened cleanly")
            return out
    except (zipfile.BadZipFile, OSError):
        out.note(
            "the file's internal index was damaged — this is what Word reports as "
            "a corrupt document — so the content was read directly from inside it"
        )

    # Damaged container. Re-opening a slice does not help -- a truncated ZIP has
    # no central directory anywhere in it -- so read the local file headers by
    # hand and inflate each member's stream directly.
    found, partial = _recover_by_local_headers(data, out)
    if found:
        out.note(f"found and read {plural(found, 'section')} of the file this way")
    else:
        out.lost("no readable parts could be found inside the file")
    return out


def _inflate_as_far_as_it_goes(body: bytes) -> tuple[bytes, bool]:
    """Inflate a stream, keeping whatever came out before it went wrong.

    `decompressobj().decompress(whole)` raises when the damage is *inside* the
    stream, and throws away everything it had already produced along with it.
    Feeding it in chunks keeps the prefix. For bit rot in the middle of a body
    that is the difference between half a document and none of it.
    """
    obj = zlib.decompressobj(-zlib.MAX_WBITS)
    out = bytearray()
    for i in range(0, len(body), 4096):
        try:
            out += obj.decompress(body[i:i + 4096])
        except zlib.error:
            return bytes(out), True
    return bytes(out), False


def _recover_by_local_headers(data: bytes, out: "Salvage") -> tuple[int, int]:
    """Walk the local file headers and inflate what each one points at.

    The central directory sits at the END of a ZIP, so a truncated download
    loses it first while the members themselves are still largely intact. Each
    local header carries its own name, method and sizes, which is enough.
    """
    import struct

    found = partial = 0
    for match in re.finditer(re.escape(_LOCAL_HEADER), data):
        start = match.start()
        header = data[start:start + 30]
        if len(header) < 30:
            continue
        try:
            (_, _, flags, method, _, _, _, comp_size, uncomp_size,
             name_len, extra_len) = struct.unpack("<IHHHHHIIIHH", header)
        except struct.error:
            continue

        name_start = start + 30
        name = data[name_start:name_start + name_len]
        if len(name) < name_len:
            continue
        try:
            filename = name.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if not filename or filename.endswith("/") or filename in out.members:
            continue

        body_start = name_start + name_len + extra_len
        # Bit 3 means the sizes were written after the data, in a descriptor we
        # cannot rely on here -- so take everything to the next header instead.
        if flags & 0x08 or comp_size == 0:
            nxt = data.find(_LOCAL_HEADER, body_start)
            body = data[body_start:nxt if nxt != -1 else len(data)]
        else:
            body = data[body_start:body_start + comp_size]

        was_short = len(body) < comp_size
        if method == 0:
            content, went_bad = body, False
        elif method == 8:
            content, went_bad = _inflate_as_far_as_it_goes(body)
        else:
            continue
        was_short = was_short or went_bad

        if not content:
            continue
        out.members[filename] = content
        found += 1
        if was_short or (uncomp_size and len(content) < uncomp_size):
            partial += 1
            # A part we rebuild from scratch anyway carries none of the owner's
            # content, so listing it as a loss would tell someone they lost
            # something they did not.
            if filename not in REBUILDABLE:
                out.lost(
                    f"one section of the file ({filename}) was cut short by the "
                    "damage and was recovered only up to the break"
                )
    return found, partial


def repair_xml(raw: bytes) -> tuple[bytes, list[str]]:
    """Fix the XML faults a strict parser refuses to look past."""
    notes: list[str] = []
    fixed = raw

    if fixed.startswith(b"\xef\xbb\xbf"):
        fixed = fixed[3:]
        notes.append("removed a byte-order mark that was placed before the XML declaration")

    fixed, fixed_decl = _repair_declaration(fixed)
    if fixed_decl:
        notes.append("repaired the line at the top of the document that says how it "
                     "is encoded")

    cleaned, n = _ILLEGAL_XML.subn(b"", fixed)
    if n:
        fixed = cleaned
        notes.append(f"removed {plural(n, 'invalid character')} that were breaking the document")

    cleaned, n = _BARE_AMP.subn(b"&amp;", fixed)
    if n:
        fixed = cleaned
        notes.append(f"repaired {plural(n, 'stray ampersand')}")

    closed, added = _close_open_tags(fixed)
    if added:
        fixed = closed
        notes.append(
            f"closed {plural(len(added), 'element')} that the damage had left open")

    return fixed, notes


_DECLARATION = re.compile(rb"^<\?xml[^>]*\?>")
_GOOD_DECLARATION = re.compile(
    rb'^<\?xml\s+version="1\.[0-9]"'
    rb'(?:\s+encoding="(?:UTF-8|utf-8|UTF-16|utf-16)")?'
    rb'(?:\s+standalone="(?:yes|no)")?\s*\?>')
_STANDARD = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def _repair_declaration(raw: bytes) -> tuple[bytes, bool]:
    """Replace a declaration a parser will refuse with the standard one.

    An encoding that does not exist, an unquoted attribute, a misspelt
    `standalone` -- a strict parser rejects the whole document over any of
    them, and none of them says anything about the owner's words. The parts
    this package writes are UTF-8, and a part it is reading declared something
    a parser would not accept is a part whose declaration cannot be trusted
    anyway, so it is replaced rather than patched.
    """
    match = _DECLARATION.match(raw)
    if not match or _GOOD_DECLARATION.match(raw):
        return raw, False
    return _STANDARD + raw[match.end():], True


def _close_open_tags(raw: bytes) -> tuple[bytes, list[str]]:
    """Close tags a truncated file left hanging.

    Deliberately simple: it only appends closing tags for elements still open at
    the end. It does not try to reorder or invent content -- guessing at
    structure is how a "repair" quietly changes what a document says.
    """
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return raw, []

    stack: list[str] = []
    for m in re.finditer(r"<\s*(/?)([A-Za-z_][\w:.\-]*)([^>]*?)(/?)\s*>", text):
        closing, name, attrs, self_closing = m.groups()
        if name.startswith("?") or name.startswith("!"):
            continue
        if self_closing == "/":
            continue
        if closing == "/":
            if stack and stack[-1] == name:
                stack.pop()
            elif name in stack:
                while stack and stack.pop() != name:
                    pass
        else:
            stack.append(name)

    if not stack:
        return raw, []
    tail = "".join(f"</{n}>" for n in reversed(stack))
    return raw + tail.encode("utf-8"), list(reversed(stack))


#: A text run, anchored so it cannot also match `<w:tbl>`, `<w:tr>` or `<w:tc>`.
#: The unanchored `<w:t[^>]*>` matches all three, and then runs to the next
#: `</w:t>` -- which on a document with a table pastes the table's own markup
#: into the recovered text as if the owner had typed it. BUG-066.
_TEXT_RUN = re.compile(rb"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.S)
_PARA_END = re.compile(rb"</w:p\s*>")


def text_runs(document_xml: bytes) -> list[str]:
    """Last resort: pull the text out of `<w:t>` runs with a regex.

    Used when the XML is too damaged to parse even after repair. It loses all
    structure, which is exactly why the report says so rather than presenting
    the result as a recovered document.

    One paragraph per entry, and the runs inside a paragraph are joined with
    nothing between them: Word starts a new run wherever formatting changes,
    including in the middle of a word, so *adipiscing* is stored as `adi` plus
    `piscing` and a separator between them invents a space the document never
    had.
    """
    out: list[str] = []
    for para in _PARA_END.split(document_xml):
        text = "".join(
            _unescape(m.group(1).decode("utf-8", errors="replace"))
            for m in _TEXT_RUN.finditer(para)
        )
        if text.strip():
            out.append(text)
    return out


def _unescape(s: str) -> str:
    return (s.replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&"))
