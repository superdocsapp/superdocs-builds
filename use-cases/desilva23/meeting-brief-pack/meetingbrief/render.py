"""Make calendar and mail legible to a document platform.

SuperDocs accepts `.docx`, `.htm`, `.html`, `.md`, `.pdf`, `.rtf`, `.tex` and
`.txt`. It does not accept `.ics` or `.eml` — which are, inconveniently, the two
native formats of the use case this build is named after. Reported; meanwhile
this module converts them.

The conversion turned out to be the right design rather than a workaround, for
two reasons.

**Control.** A raw `.eml` is quoted-printable bodies, MIME boundaries, forty
lines of `Received:` headers and a base64 signature image. Sending that to a
model is paying for tokens that carry no meaning and inviting it to quote a
mail server as if it were a person. Rendering first means the model sees the
sender, the date, the subject and the words — and nothing else.

**Provenance.** The rendered file is what the model reads, and the original file
is what a human checks the brief against. Keeping both, with the rendered copy
naming its origin in its first line, means a claim in the brief can always be
walked back to a real message on disk.

This is the shape the task document describes for host applications generally:
get the content out with the host's own API, send it as a file, and never expect
the platform to understand a format it never claimed to.
"""

from __future__ import annotations

import email
import email.policy
import re
from email.message import EmailMessage
from pathlib import Path

CONVERTED_SUFFIX = ".md"


def render_eml(path: Path) -> str:
    """An email thread as readable Markdown.

    Uses Python's own parser rather than regex, because MIME is a real format
    and a hand-rolled reader gets multipart, encodings and folded headers wrong
    in ways that are invisible until a brief quotes mojibake at an executive.
    """
    message: EmailMessage = email.message_from_bytes(
        path.read_bytes(), policy=email.policy.default
    )

    body_part = message.get_body(preferencelist=("plain", "html"))
    body = body_part.get_content() if body_part else ""

    if body_part is not None and body_part.get_content_type() == "text/html":
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"[ \t]{2,}", " ", body)

    # Quoted history is kept — a thread's earlier turns are frequently where the
    # commitment being reviewed was actually made — but marked, so the model can
    # tell a reply from the message it replies to.
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        lines.append(f"> {stripped.lstrip('> ').rstrip()}" if stripped.startswith(">")
                     else stripped)

    header = [
        f"<!-- rendered from {path.name} for upload; the original is the source of record -->",
        f"# Email: {message.get('Subject', '(no subject)')}",
        "",
        f"**From:** {message.get('From', 'unknown')}  ",
        f"**To:** {message.get('To', 'unknown')}  ",
    ]
    if message.get("Cc"):
        header.append(f"**Cc:** {message.get('Cc')}  ")
    header += [f"**Date:** {message.get('Date', 'unknown')}", "", "---", ""]

    return "\n".join(header + lines).rstrip() + "\n"


def render_ics(path: Path) -> str:
    """A calendar invitation as readable Markdown."""
    raw = path.read_text(encoding="utf-8")
    unfolded = re.sub(r"\r?\n[ \t]", "", raw)

    def value(name: str) -> str:
        match = re.search(rf"^{name}(?:;[^:]*)?:(.*)$", unfolded, re.MULTILINE)
        return match.group(1).strip() if match else ""

    def person(line: str) -> str:
        name = re.search(r"CN=([^;:]+)", line)
        mail = re.search(r"mailto:([^\s;]+)", line, re.IGNORECASE)
        role = re.search(r"ROLE=([^;:]+)", line)
        who = name.group(1).strip() if name else (mail.group(1) if mail else "unknown")
        address = f" <{mail.group(1).strip()}>" if mail else ""
        as_what = f" — {role.group(1).strip().lower().replace('-', ' ')}" if role else ""
        return f"- {who}{address}{as_what}"

    when = value("DTSTART")
    pretty = when
    match = re.match(r"^(\d{4})(\d\d)(\d\d)T(\d\d)(\d\d)", when)
    if match:
        y, mo, d, h, mi = match.groups()
        pretty = f"{y}-{mo}-{d} {h}:{mi}" + (" UTC" if when.endswith("Z") else "")

    attendees = [person(line) for line in re.findall(r"^ATTENDEE.*$", unfolded, re.MULTILINE)]
    description = value("DESCRIPTION").replace("\\n", "\n").replace("\\,", ",")

    out = [
        f"<!-- rendered from {path.name} for upload; the original is the source of record -->",
        f"# Meeting invitation: {value('SUMMARY') or '(no title)'}",
        "",
        f"**When:** {pretty or 'not stated'}  ",
        f"**Location:** {value('LOCATION') or 'not stated'}  ",
    ]
    organiser = re.search(r"^ORGANIZER.*$", unfolded, re.MULTILINE)
    if organiser:
        out.append(f"**Organiser:** {person(organiser.group(0)).lstrip('- ')}")
    out += ["", "## Attendees", ""] + (attendees or ["- none listed"])
    if description:
        out += ["", "## From the invitation", "", description.strip()]

    return "\n".join(out).rstrip() + "\n"


RENDERERS = {".eml": render_eml, ".ics": render_ics}


def prepare_for_upload(path: Path, workdir: Path) -> tuple[Path, bool]:
    """Return a path the API will accept, converting only when it must.

    Returns `(path, converted)`. Formats SuperDocs already takes are passed
    through untouched — converting a `.docx` to Markdown to satisfy a rule that
    does not apply would throw away the tables and styling the platform is
    specifically good at preserving.
    """
    renderer = RENDERERS.get(path.suffix.lower())
    if renderer is None:
        return path, False

    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / (path.stem + CONVERTED_SUFFIX)
    target.write_text(renderer(path), encoding="utf-8")
    return target, True
