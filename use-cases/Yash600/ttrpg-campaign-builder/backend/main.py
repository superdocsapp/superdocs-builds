"""
main.py -- FastAPI app for the TTRPG campaign-doc builder, v2.

v1 auto-seeded one hardcoded campaign at startup and tracked coherence via
chunk-level Entity/Reference hashing (see git history / seed.py, now
retired). v2 removes ALL auto-ingestion: a Campaign starts completely
empty, and every Document/Character/NPC/Location is created or imported by
the user through these endpoints. See models.py's module docstring for the
full data-model rationale (whole-document versioning, user-defined
DocumentLink edges, staleness-by-version-number).

Endpoint groups:

  Campaigns        POST/GET /campaigns, GET /campaigns/{id}, nested lists
  Documents        create (blank) + import (file upload w/ explicit type
                    picker -- no auto-classification), read, version
                    history, export
  Chat / editing    POST /documents/{id}/chat -- chat_async + poll, produces
                    a PROPOSED DocumentVersion; approve/reject endpoints
                    flip it to ACTIVE (archiving the old one) or discard it,
                    exactly mirroring a SuperDocs chat_async job's
                    awaiting_approval -> approved/rejected lifecycle
  Characters/NPCs/  each is a thin entity row 1:1 with its own backing
  Locations         Document, created in one call (entity + Document +
                    DocumentVersion v1 ACTIVE)
  Illustrations     Pollinations (free, keyless) generation -> SuperDocs
                    image upload -> optional embed via a synchronous chat
                    edit against the entity's own backing document
  Links             user-defined DocumentLink edges (no AI auto-discovery
                    per the spec); staleness tracked by comparing
                    synced_version_number against the target's live active
                    version number
  Export/Validate   per-document and whole-campaign (zip, with a manifest)
                    export; a local-only validator that recomputes link
                    staleness on demand
"""

from __future__ import annotations

import io
import logging
import os
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session, select

import chunking
import db
import image_gen
import models
from superdocs_client import SuperDocsClient, SuperDocsError

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ttrpg.images")

app = FastAPI(title="TTRPG Campaign Builder API (v2 -- user-fed)")

# Origins allowed to call this API. Defaults to localhost (any port, for
# local dev) plus any Vercel deployment (preview or prod -- Vercel gives
# every branch/PR its own *.vercel.app subdomain, so a fixed single-origin
# allowlist would break on the very first preview deploy). Override with a
# real regex via CORS_ORIGIN_REGEX once you have a custom domain, e.g.
# CORS_ORIGIN_REGEX='https://(www\.)?your-domain\.com' -- see README's
# Deployment section.
_CORS_ORIGIN_REGEX = os.environ.get(
    "CORS_ORIGIN_REGEX",
    r"http://localhost:\d+|https://.*\.vercel\.app",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------------- #
# locally re-hosted illustration bytes
# -------------------------------------------------------------------------- #
#
# SuperDocs' images/upload-base64 endpoint is documented to return a "stable
# public URL", but in practice the returned storage.googleapis.com link can
# come back with the underlying GCS object's ACL not actually public --
# anonymous browser fetches 403 with AccessDenied even though the upload
# call itself succeeded. That's a platform-side bucket-permissions issue on
# SuperDocs' end, confirmed by fetching the exact URL it returned. Since we
# already hold the raw bytes in memory when we generate/receive an
# illustration, we also save our own copy and serve it from this backend --
# so the in-app gallery renders regardless of whether SuperDocs' bucket ACL
# is behaving. The SuperDocs-returned URL is still what gets embedded into
# the document itself (see generate_illustration/upload_illustration below),
# since that's the URL SuperDocs' own editor/export pipeline resolves.
ILLUSTRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "illustration_assets")
os.makedirs(ILLUSTRATIONS_DIR, exist_ok=True)
app.mount("/static/illustrations", StaticFiles(directory=ILLUSTRATIONS_DIR), name="illustration_assets")


def _save_local_illustration(image_bytes: bytes, ext: str) -> str:
    """Writes image_bytes to ILLUSTRATIONS_DIR under a fresh unique filename
    and returns just the filename (stored on Illustration.local_image_path;
    turned into a full URL by _local_image_url at read time)."""
    ext = (ext or "jpg").lstrip(".").split(";")[0].strip() or "jpg"
    filename = f"{models._uuid()}.{ext}"
    with open(os.path.join(ILLUSTRATIONS_DIR, filename), "wb") as f:
        f.write(image_bytes)
    return filename


def _local_image_url(local_image_path: str | None) -> str | None:
    if not local_image_path:
        return None
    base = os.environ.get("PUBLIC_BACKEND_BASE", "http://localhost:8001").strip().rstrip("/")
    return f"{base}/static/illustrations/{local_image_path}"


def get_client() -> SuperDocsClient:
    api_key = os.environ.get("SUPERDOCS_API_KEY", "").strip()
    base_url = os.environ.get("SUPERDOCS_API_BASE", "https://api.superdocs.app").strip()
    if not api_key:
        raise HTTPException(500, "SUPERDOCS_API_KEY not configured")
    return SuperDocsClient(api_key=api_key, base_url=base_url)


@app.on_event("startup")
def on_startup():
    db.init_db()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -------------------------------------------------------------------------- #
# request bodies
# -------------------------------------------------------------------------- #


class CampaignCreate(BaseModel):
    name: str
    description: str = ""
    genre: str = ""
    setting: str = ""


class CampaignPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    genre: Optional[str] = None
    setting: Optional[str] = None


class DocumentCreate(BaseModel):
    doc_type: models.DocumentType
    title: str
    description: str = ""
    content_html: str = ""


class DocumentPatch(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    doc_type: Optional[models.DocumentType] = None


class DocumentSaveIn(BaseModel):
    content_html: str
    change_summary: str = "Manual edit"


class EntityCreate(BaseModel):
    name: str
    description: str = ""
    content_html: str = ""
    # Character-only
    race: str = ""
    char_class: str = ""
    level: Optional[int] = None
    # NPC-only
    role: str = ""
    related_location_id: Optional[str] = None


class LinkCreate(BaseModel):
    source_document_id: str
    target_document_id: str
    relationship_type: models.LinkRelationshipType = models.LinkRelationshipType.RELATED_TO
    note: str = ""


class ChatIn(BaseModel):
    message: str


def _apply_pending_change(candidate_html: str, pc) -> tuple[str, bool]:
    """Merge one SuperDocs PendingChange into candidate_html for local preview.

    Pending changes come in a few different shapes depending on what kind of
    edit the AI proposed:
      - replace: old_html is real content that already exists in the
        document, new_html is what it should become -- find/replace.
      - insert/append (e.g. "add a new Summary section"): there's nothing to
        find because the content is brand new, so old_html is empty/None and
        new_html is the chunk to add -- append it to the end of the doc.
      - delete: new_html is empty/None, old_html should simply be removed.

    Returns (new_candidate_html, applied). applied=False means this change
    could not be merged (e.g. a replace/delete whose old_html text no longer
    matches the current document) so the caller can surface that instead of
    silently dropping it and presenting an unchanged "proposal".
    """
    operation = (pc.operation or "").lower()
    old_html = (pc.old_html or "").strip()
    new_html = pc.new_html if pc.new_html is not None else ""

    is_insert = (not old_html) or operation in ("insert", "insert_after", "insert_before", "append", "add", "create")

    if is_insert:
        if not new_html.strip():
            return candidate_html, False
        separator = "\n" if candidate_html and not candidate_html.endswith("\n") else ""
        return candidate_html + separator + new_html, True

    if pc.old_html and pc.old_html in candidate_html:
        return candidate_html.replace(pc.old_html, new_html, 1), True

    return candidate_html, False


class IllustrationCreate(BaseModel):
    entity_type: models.IllustrationEntityType
    entity_id: str
    prompt: str
    embed: bool = True
    width: int = 1024
    height: int = 1024
    seed: Optional[int] = None


# -------------------------------------------------------------------------- #
# serialization helpers
# -------------------------------------------------------------------------- #


def _campaign_out(c: models.Campaign) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "genre": c.genre,
        "setting": c.setting,
        "cover_image": c.cover_image,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


def _version_out(v: models.DocumentVersion, include_content: bool = True) -> dict:
    out = {
        "id": v.id,
        "document_id": v.document_id,
        "version_number": v.version_number,
        "status": v.status,
        "change_summary": v.change_summary,
        "created_by": v.created_by,
        "pending_job_id": v.pending_job_id,
        "pending_change_id": v.pending_change_id,
        "created_at": v.created_at,
    }
    if include_content:
        out["content_html"] = v.content_html
        out["content_text"] = v.content_text
    return out


def _doc_out(d: models.Document, active_version: models.DocumentVersion | None = None) -> dict:
    out = {
        "id": d.id,
        "campaign_id": d.campaign_id,
        "doc_type": d.doc_type,
        "title": d.title,
        "description": d.description,
        "origin": d.origin,
        "superdocs_document_id": d.superdocs_document_id,
        "superdocs_session_id": d.superdocs_session_id,
        "active_version_id": d.active_version_id,
        "created_at": d.created_at,
        "updated_at": d.updated_at,
    }
    if active_version is not None:
        out["active_version"] = _version_out(active_version)
    return out


def _link_out(l: models.DocumentLink) -> dict:
    return {
        "id": l.id,
        "source_document_id": l.source_document_id,
        "target_document_id": l.target_document_id,
        "relationship_type": l.relationship_type,
        "note": l.note,
        "synced_version_number": l.synced_version_number,
        "status": l.status,
        "created_at": l.created_at,
        "last_checked_at": l.last_checked_at,
    }


def _character_out(c: models.Character) -> dict:
    return {
        "id": c.id,
        "campaign_id": c.campaign_id,
        "document_id": c.document_id,
        "name": c.name,
        "race": c.race,
        "char_class": c.char_class,
        "level": c.level,
        "image_url": c.image_url,
        "created_at": c.created_at,
    }


def _npc_out(n: models.NPC) -> dict:
    return {
        "id": n.id,
        "campaign_id": n.campaign_id,
        "document_id": n.document_id,
        "name": n.name,
        "role": n.role,
        "related_location_id": n.related_location_id,
        "image_url": n.image_url,
        "created_at": n.created_at,
    }


def _location_out(loc: models.Location) -> dict:
    return {
        "id": loc.id,
        "campaign_id": loc.campaign_id,
        "document_id": loc.document_id,
        "name": loc.name,
        "image_url": loc.image_url,
        "created_at": loc.created_at,
    }


def _illustration_out(i: models.Illustration) -> dict:
    return {
        "id": i.id,
        "campaign_id": i.campaign_id,
        "entity_type": i.entity_type,
        "entity_id": i.entity_id,
        "prompt": i.prompt,
        "provider": i.provider,
        "superdocs_image_url": i.superdocs_image_url,
        "local_image_url": _local_image_url(i.local_image_path),
        "embedded_in_document_id": i.embedded_in_document_id,
        "embedded": i.embedded,
        "created_at": i.created_at,
    }


def _chat_message_out(m: models.ChatMessage) -> dict:
    return {
        "id": m.id,
        "chat_session_id": m.chat_session_id,
        "role": m.role,
        "content": m.content,
        "result_document_id": m.result_document_id,
        "result_version_id": m.result_version_id,
        "created_at": m.created_at,
    }


def _event_out(ev: models.ChangeEvent) -> dict:
    return {
        "id": ev.id,
        "event_type": ev.event_type,
        "timestamp": ev.timestamp,
        "campaign_id": ev.campaign_id,
        "document_id": ev.document_id,
        "link_id": ev.link_id,
        "actor": ev.actor,
        "description": ev.description,
        "approved": ev.approved,
    }


# -------------------------------------------------------------------------- #
# internal helpers
# -------------------------------------------------------------------------- #

_DOC_TYPE_SUBFOLDER = {
    models.DocumentType.CAMPAIGN_BIBLE: "",
    models.DocumentType.CHARACTER: "Characters/",
    models.DocumentType.NPC: "NPCs/",
    models.DocumentType.LOCATION: "Locations/",
    models.DocumentType.SESSION_LOG: "Sessions/",
    models.DocumentType.OTHER: "Other/",
}

DOC_TYPE_MANIFEST_LABELS = {
    models.DocumentType.CAMPAIGN_BIBLE: "Campaign Bible",
    models.DocumentType.CHARACTER: "Character Sheet",
    models.DocumentType.NPC: "NPC Dossier",
    models.DocumentType.LOCATION: "Location Dossier",
    models.DocumentType.SESSION_LOG: "Session Log",
    models.DocumentType.OTHER: "Document",
}

_EXPORT_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "html": "text/html",
    "markdown": "text/markdown",
    "txt": "text/plain",
    "zip": "application/zip",
}


def _safe_filename(title: str, extension: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("_") or "document"
    return f"{stem}.{extension}"


def _numbered_filename(index: int, title: str, extension: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("_") or "document"
    return f"{index:02d}_{stem}.{extension}"


# -------------------------------------------------------------------------- #
# [[Reference]] detection -- wiki-style cross-links inside document prose
# -------------------------------------------------------------------------- #

_REFERENCE_PATTERN = re.compile(r"\[\[([^\[\]]+?)\]\]")


def _describe_broken_refs(broken_refs: list[dict]) -> str:
    parts = [f"[[{b['ref_title']}]] in {b['document_title']}" for b in broken_refs[:5]]
    return ", ".join(parts)


def _normalize_title(s: str) -> str:
    """
    Loosens title matching beyond exact-string-equality so [[Reference]]
    resolution survives the single most common real-world mismatch: a
    document imported from a file keeps the raw filename as its title (e.g.
    "02_Character_Sheet_Aric_Stormborn" from "02_Character_Sheet_Aric_
    Stormborn.docx"), while a human writing [[Aric Stormborn]] in prose
    naturally won't retype that whole filename. Strips a leading numeric
    prefix ("02_", "2.", "02 -"), turns underscores/hyphens into spaces,
    collapses whitespace, and lowercases -- purely a lookup-key transform,
    never touches what's actually stored or displayed.
    """
    s = s.strip().lower()
    s = re.sub(r"^\d+[_.\-\s]+", "", s)
    s = re.sub(r"[_\-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


_TR_PATTERN = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_PATTERN = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
_TAG_STRIP_PATTERN = re.compile(r"<[^>]+>")
_DOC_ID_LABELS = {"document id", "doc id", "id"}


def _strip_html_tags(html: str) -> str:
    return _TAG_STRIP_PATTERN.sub(" ", html).strip()


def _extract_document_id(content_html: str) -> str | None:
    """
    Some authored/imported content carries its own internal "Document ID"
    in a metadata table (e.g. a CONTROL/DETAIL table with a row reading
    "Document ID | SC-PC-ARIC") -- an ID scheme that predates this app's
    title-based [[Reference]] syntax. [[SC-PC-ARIC]] elsewhere in the
    campaign is a reference to THIS document by that internal ID, not by
    its (often much longer, filename-derived) title -- so without reading
    this field, that whole class of reference can never resolve no matter
    how forgiving title matching gets. Best-effort HTML table scan (not a
    full parser), good enough for the row shapes docx-import/SuperDocs
    export produce.
    """
    for tr in _TR_PATTERN.finditer(content_html):
        cells = _CELL_PATTERN.findall(tr.group(1))
        if len(cells) < 2:
            continue
        label = _strip_html_tags(cells[0]).lower()
        if label in _DOC_ID_LABELS:
            value = _strip_html_tags(cells[1])
            if value:
                return value
    return None


_HEADING_PATTERN = re.compile(r"<(h[1-4])([^>]*)>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
_HEADING_ID_PATTERN = re.compile(r'<(h[1-4])\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</\1>', re.IGNORECASE | re.DOTALL)
_ID_ATTR_PATTERN = re.compile(r'\bid\s*=\s*"[^"]*"', re.IGNORECASE)
_LEADING_NUM_PATTERN = re.compile(r"^\d+[-_.\s]*")
_ENTITY_PREFIX_PATTERN = re.compile(r"^[A-Za-z]{2,5}-(.+)$")
_ID_STYLE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:[-:][A-Z0-9]+)+$")


def _slugify(text: str) -> str:
    text = _strip_html_tags(text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "section"


def _ensure_heading_anchors(content_html: str) -> str:
    """
    Gives every heading (h1-h4) that doesn't already carry an id= attribute a
    stable slug id, e.g. <h2>Magic, Oaths, and the Ward Network</h2> becomes
    <h2 id="magic-oaths-and-the-ward-network">...</h2>. This is what makes a
    [[DOC-ID:SECTION-ID]] reference from another document able to jump
    straight to that section instead of just opening the document at the
    top. Idempotent -- an existing id is left untouched so re-running this
    (every time a document is saved) doesn't churn stable anchors that
    something else may already be linking to.
    """
    seen: dict[str, int] = {}

    def _add_id(m: "re.Match") -> str:
        tag, attrs, inner = m.group(1), m.group(2), m.group(3)
        if _ID_ATTR_PATTERN.search(attrs):
            return m.group(0)
        slug = _slugify(inner)
        if slug in seen:
            seen[slug] += 1
            slug = f"{slug}-{seen[slug]}"
        else:
            seen[slug] = 0
        return f'<{tag}{attrs} id="{slug}">{inner}</{tag}>'

    return _HEADING_PATTERN.sub(_add_id, content_html)


def _heading_entries(content_html: str) -> list[tuple[str, str]]:
    """[(anchor_slug, heading_text), ...] for every heading that already
    carries an id (see _ensure_heading_anchors)."""
    return [(m.group(2), _strip_html_tags(m.group(3))) for m in _HEADING_ID_PATTERN.finditer(content_html)]


def _section_keyword(section_code: str) -> str:
    """'6-MAGIC' -> 'magic', '10-GM-SECRETS' -> 'gm secrets',
    'SESSION-3' -> 'session 3' -- the section half of a [[DOC:SECTION]]
    reference, loosened for matching against a heading inside that doc."""
    s = _LEADING_NUM_PATTERN.sub("", section_code.strip().lower())
    return re.sub(r"[-_]+", " ", s).strip()


def _entity_keyword(entity_code: str) -> str:
    """'LOC-VEYR' -> 'veyr', 'FAC-LANTERN' -> 'lantern' -- strips a short
    all-letters entity-type prefix (LOC/FAC/THR/NPC/...) so the remainder
    can be matched against headings across the campaign's documents."""
    m = _ENTITY_PREFIX_PATTERN.match(entity_code.strip())
    s = m.group(1) if m else entity_code.strip()
    return re.sub(r"[-_]+", " ", s.lower()).strip()


def _document_sections(content_html: str) -> list[tuple[str | None, str]]:
    """Splits content_html into (anchor_slug_or_None, section_text) chunks --
    one per heading (h1-h4) plus everything up to the next heading, so a
    section's full body can be searched, not just its heading text. Needed
    for entries like "Veyr, City of Rain" that are named in prose under a
    "Key Locations" heading rather than being a heading of their own."""
    matches = list(_HEADING_PATTERN.finditer(content_html))
    sections: list[tuple[str | None, str]] = []
    for i, m in enumerate(matches):
        attrs, inner = m.group(2), m.group(3)
        id_match = _ID_ATTR_PATTERN.search(attrs)
        anchor = None
        if id_match:
            val = re.search(r'"([^"]*)"', id_match.group(0))
            anchor = val.group(1) if val else None
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(content_html)
        body_text = _strip_html_tags(content_html[body_start:body_end])
        sections.append((anchor, f"{_strip_html_tags(inner)} {body_text}"))
    return sections


def _resolve_section_anchor(content_html: str, keyword: str) -> tuple[str, str] | None:
    """
    Loosely match `keyword` (see _section_keyword/_entity_keyword) against
    this document, trying two tiers:

      1. The keyword appears in a heading's own text -- most precise. If
         it matches more than one heading, stop here rather than falling
         through to the looser tier and compounding the ambiguity.
      2. The keyword appears anywhere in a section's body (heading text +
         everything up to the next heading) -- catches entries named in
         prose under a broader heading (e.g. "Veyr, City of Rain" under
         "Key Locations") rather than being a heading themselves.

    Returns (anchor_slug, heading_text) only when exactly one match is
    found; an ambiguous match is left unresolved rather than guessed, same
    policy as _resolve_title's substring pass.
    """
    if not keyword:
        return None
    pattern = re.compile(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)")
    headings = _heading_entries(content_html)

    heading_matches = [(slug, text) for slug, text in headings if pattern.search(_normalize_title(text))]
    if len(heading_matches) == 1:
        return heading_matches[0]
    if len(heading_matches) > 1:
        return None

    heading_by_anchor = dict(headings)
    body_matches = [anchor for anchor, text in _document_sections(content_html) if anchor and pattern.search(_normalize_title(text))]
    body_matches = list(dict.fromkeys(body_matches))
    if len(body_matches) == 1:
        anchor = body_matches[0]
        return anchor, heading_by_anchor.get(anchor, anchor)
    return None


def _looks_like_id_code(raw_title: str) -> bool:
    """True for bracket text that's an internal ID-style code (e.g.
    'SC-BIBLE:6-MAGIC', 'LOC-VEYR') rather than a human-written title (e.g.
    'Aric Stormborn'). Only ID-style codes get their raw [[text]] swapped
    for a clean readable label -- human titles are already readable."""
    return bool(_ID_STYLE_PATTERN.match(raw_title.strip()))


@dataclass
class _RefResolution:
    document: "models.Document"
    anchor: str | None
    label: str


def _resolve_reference(session: Session, raw_title: str, docs: list["models.Document"]) -> "_RefResolution | None":
    """
    Full resolution for a [[...]] reference, layered on top of
    _resolve_title's document-level passes:

      A. raw_title (optionally "DOC:SECTION") resolves to a document via
         _resolve_title. If there's a ":SECTION" half, additionally try to
         match it to a heading inside that document (_section_keyword) so
         the link can jump straight to that section, not just the doc top.
      B. If no document resolves at all -- the normal case for this pack's
         bare entity/location/faction/thread codes like LOC-VEYR, FAC-
         LANTERN, THR-KAEL, which only exist as *sections inside* another
         document (typically the Campaign Bible), never as their own
         document -- search every other document's headings for a loose
         keyword match (_entity_keyword). Resolves only when exactly one
         document has a matching heading; refuses to guess across several.
    """
    doc_part, _, section_part = raw_title.partition(":")
    doc_part = doc_part.strip()

    target = _resolve_title(session, raw_title, docs)
    if target is not None:
        anchor = None
        heading_text = None
        if section_part:
            active = _active_version(session, target)
            if active is not None:
                found = _resolve_section_anchor(active.content_html, _section_keyword(section_part))
                if found:
                    anchor, heading_text = found
        label = target.title if not heading_text else f"{target.title}: {heading_text}"
        return _RefResolution(target, anchor, label)

    keyword = _entity_keyword(doc_part)
    if not keyword:
        return None

    found_in: list[tuple["models.Document", str, str]] = []
    for d in docs:
        active = _active_version(session, d)
        if active is None:
            continue
        found = _resolve_section_anchor(active.content_html, keyword)
        if found:
            found_in.append((d, found[0], found[1]))

    if len(found_in) == 1:
        d, anchor, heading_text = found_in[0]
        return _RefResolution(d, anchor, f"{d.title}: {heading_text}")
    if len(found_in) > 1:
        # Ambiguous across documents -- prefer the campaign bible, since
        # that's this pack's canonical "world index" convention.
        bible_matches = [f for f in found_in if f[0].doc_type == models.DocumentType.CAMPAIGN_BIBLE]
        if len(bible_matches) == 1:
            d, anchor, heading_text = bible_matches[0]
            return _RefResolution(d, anchor, f"{d.title}: {heading_text}")
    return None


def _resolve_title(session: Session, raw_title: str, docs: list[models.Document]) -> models.Document | None:
    """
    Resolve a [[raw_title]] reference against a list of candidate documents,
    trying progressively looser matches until exactly one document is found:

      1. Exact, case-insensitive title match.
      2. Exact match after normalizing both sides (see _normalize_title) --
         catches a leading numeric export-style prefix and underscore-vs-
         space differences.
      3. Whole-word substring: the normalized reference text appears as a
         contiguous, word-bounded run inside a normalized document title --
         e.g. [[Aric Stormborn]] matching a document literally titled
         "02_Character_Sheet_Aric_Stormborn". Only applied when exactly one
         document matches this way; an ambiguous substring match (multiple
         documents contain the same words) is left unresolved rather than
         guessed, since silently linking to the wrong document is worse
         than flagging the reference as unresolved.
      4. Internal "Document ID" field match (see _extract_document_id) --
         handles bracket text that's an internal ID like SC-PC-ARIC rather
         than a title at all, optionally with a ":section-anchor" suffix
         (e.g. SC-BIBLE:10-GM-SECRETS resolves to the SC-BIBLE document
         here; _resolve_reference layers section-anchor matching for that
         suffix on top of this, and also handles bare entity/location/
         faction/thread codes that never match a document at all).
    """
    needle_exact = raw_title.strip().lower()
    for d in docs:
        if d.title.strip().lower() == needle_exact:
            return d

    needle_norm = _normalize_title(raw_title)
    if needle_norm:
        for d in docs:
            if _normalize_title(d.title) == needle_norm:
                return d

        pattern = re.compile(r"(?<!\w)" + re.escape(needle_norm) + r"(?!\w)")
        substring_matches = [d for d in docs if pattern.search(_normalize_title(d.title))]
        if len(substring_matches) == 1:
            return substring_matches[0]

    id_needle = raw_title.strip().split(":", 1)[0].strip().lower()
    if id_needle:
        for d in docs:
            active = _active_version(session, d)
            if active is None:
                continue
            doc_id = _extract_document_id(active.content_html)
            if doc_id and doc_id.strip().lower() == id_needle:
                return d

    return None


def _resolve_and_linkify_references(
    session: Session, doc: models.Document, content_html: str
) -> tuple[str, list[str], list[str]]:
    """
    First backfills stable anchor ids onto this document's own headings
    (_ensure_heading_anchors) -- needed so OTHER documents' [[DOC:SECTION]]
    references can jump into a section here, not just this document's top.

    Then scans content_html for [[Title]] / [[DOC-ID:SECTION-ID]] / bare
    entity-code patterns and resolves each via _resolve_reference against
    other documents in the same campaign (see that function + _resolve_title
    for the full pass list: exact/normalized/substring title match,
    internal "Document ID" field match, DOC:SECTION anchor match, and bare
    entity/location/faction/thread code match against any document's
    headings). Resolved matches are rewritten into clickable anchors --
    with a clean human-readable label swapped in for ID-style codes (e.g.
    "SC-BIBLE:6-MAGIC" displays as "Campaign Bible: Magic, Oaths, and the
    Ward Network"), while human-written [[Title]] references keep showing
    exactly what was typed. Unresolved matches are wrapped in a
    "broken-reference" span so the frontend can style + warn on them
    without needing a second pass. Returns (rewritten_html,
    resolved_target_document_ids, broken_titles). Does NOT touch
    DocumentLink rows itself -- see _sync_reference_links.
    """
    content_html = _ensure_heading_anchors(content_html)
    campaign_docs = session.exec(
        select(models.Document).where(
            models.Document.campaign_id == doc.campaign_id,
            models.Document.id != doc.id,
        )
    ).all()
    resolved_ids: list[str] = []
    broken_titles: list[str] = []

    def _replace(m: "re.Match") -> str:
        raw_title = m.group(1).strip()
        resolution = _resolve_reference(session, raw_title, campaign_docs)
        if resolution is None:
            if raw_title not in broken_titles:
                broken_titles.append(raw_title)
            return f'<span class="broken-reference" title="No document or section matches &quot;{raw_title}&quot;">[[{raw_title}]]</span>'
        if resolution.document.id not in resolved_ids:
            resolved_ids.append(resolution.document.id)
        href = f"/documents/{resolution.document.id}"
        if resolution.anchor:
            href += f"#{resolution.anchor}"
        display_text = resolution.label if _looks_like_id_code(raw_title) else raw_title
        return (
            f'<a class="doc-reference" href="{href}" data-ref-title="{raw_title}" title="{resolution.label}">'
            f"{display_text}</a>"
        )

    rewritten = _REFERENCE_PATTERN.sub(_replace, content_html)
    return rewritten, resolved_ids, broken_titles


def _sync_reference_links(session: Session, source_doc: models.Document, resolved_target_ids: list[str]) -> None:
    """
    Replaces every auto-detected REFERENCES-type link FROM source_doc with a
    fresh set matching resolved_target_ids. Manual links (created through
    POST /links) are untouched -- auto links are identified by
    relationship_type == REFERENCES and note == "[[auto]]", a lightweight
    marker that avoids a schema change to distinguish auto from manual.
    """
    existing_auto = session.exec(
        select(models.DocumentLink).where(
            models.DocumentLink.source_document_id == source_doc.id,
            models.DocumentLink.relationship_type == models.LinkRelationshipType.REFERENCES,
            models.DocumentLink.note == "[[auto]]",
        )
    ).all()
    existing_by_target = {l.target_document_id: l for l in existing_auto}

    for target_id in resolved_target_ids:
        if target_id in existing_by_target:
            continue
        target = session.get(models.Document, target_id)
        if target is None:
            continue
        target_active = _active_version(session, target)
        link = models.DocumentLink(
            source_document_id=source_doc.id,
            target_document_id=target_id,
            relationship_type=models.LinkRelationshipType.REFERENCES,
            note="[[auto]]",
            synced_version_number=target_active.version_number if target_active else 0,
            status=models.LinkStatus.SYNCED,
        )
        session.add(link)
        _record_event(
            session,
            models.ChangeEventType.LINK_CREATED,
            campaign_id=source_doc.campaign_id,
            document_id=source_doc.id,
            description=f"Auto-linked via [[reference]] to {target.title!r}",
        )

    for target_id, link in existing_by_target.items():
        if target_id not in resolved_target_ids:
            session.delete(link)

    session.commit()


def _get_campaign(session: Session, campaign_id: str) -> models.Campaign:
    c = session.get(models.Campaign, campaign_id)
    if c is None:
        raise HTTPException(404, f"campaign {campaign_id} not found")
    return c


def _get_document(session: Session, document_id: str) -> models.Document:
    d = session.get(models.Document, document_id)
    if d is None:
        raise HTTPException(404, f"document {document_id} not found")
    return d


def _active_version(session: Session, doc: models.Document) -> models.DocumentVersion | None:
    if not doc.active_version_id:
        return None
    return session.get(models.DocumentVersion, doc.active_version_id)


def _next_version_number(session: Session, document_id: str) -> int:
    existing = session.exec(
        select(models.DocumentVersion).where(models.DocumentVersion.document_id == document_id)
    ).all()
    return (max((v.version_number for v in existing), default=0)) + 1


def _record_event(
    session: Session,
    event_type: models.ChangeEventType,
    *,
    campaign_id: str | None = None,
    document_id: str | None = None,
    link_id: str | None = None,
    description: str = "",
    actor: str = "system",
    approved: bool | None = None,
) -> models.ChangeEvent:
    ev = models.ChangeEvent(
        event_type=event_type,
        campaign_id=campaign_id,
        document_id=document_id,
        link_id=link_id,
        actor=actor,
        description=description,
        approved=approved,
    )
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return ev


def _fresh_session_id(campaign_id: str) -> str:
    import uuid

    return f"campaign-{campaign_id[:8]}-doc-{uuid.uuid4().hex[:8]}"


def _create_document_with_version(
    session: Session,
    client: SuperDocsClient,
    *,
    campaign_id: str,
    doc_type: models.DocumentType,
    title: str,
    description: str,
    content_html: str,
    filename: str,
    is_html_text: bool,
    origin: models.DocumentOrigin,
) -> models.Document:
    """
    Every Document row is backed by exactly one dedicated SuperDocs session
    (this account's sessions reliably hold exactly one genuinely open
    document each -- see superdocs_client.py notes). Upload, then look the
    durable document up via list_session_documents + get_document to fetch
    SuperDocs' own persisted HTML (with its chunk ids baked in) rather than
    trusting our own input HTML verbatim -- that persisted HTML is what
    later chat edits will actually operate on.
    """
    sd_session_id = _fresh_session_id(campaign_id)
    client.upload_document_base64(
        filename=filename,
        html_or_bytes=content_html,
        session_id=sd_session_id,
        return_html=False,
        is_html_text=is_html_text,
    )
    roster = client.list_session_documents(sd_session_id)
    durable_id = roster["documents"][0]["durable_document_id"]
    detail = client.get_document(durable_id, include_html=True)
    persisted_html = detail.get("html") or content_html

    doc = models.Document(
        campaign_id=campaign_id,
        doc_type=doc_type,
        title=title,
        description=description,
        origin=origin,
        superdocs_document_id=durable_id,
        superdocs_session_id=sd_session_id,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)

    # Resolve any [[Reference]] wiki-links already present in the initial
    # content before the first version is written, so v1 is already linked
    # rather than needing an immediate re-save to pick them up.
    linkified_html, resolved_ids, _broken = _resolve_and_linkify_references(session, doc, persisted_html)

    version = models.DocumentVersion(
        document_id=doc.id,
        version_number=1,
        content_html=linkified_html,
        content_text=chunking.normalize_text(linkified_html),
        status=models.DocumentVersionStatus.ACTIVE,
        change_summary="Initial version",
        created_by="human" if origin != models.DocumentOrigin.GENERATED else "ai",
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    doc.active_version_id = version.id
    session.add(doc)
    session.commit()
    session.refresh(doc)

    _sync_reference_links(session, doc, resolved_ids)
    return doc


def _apply_active_version(
    session: Session,
    doc: models.Document,
    new_content_html: str,
    *,
    status: models.DocumentVersionStatus,
    change_summary: str,
    created_by: str,
    pending_job_id: str | None = None,
    pending_change_id: str | None = None,
) -> models.DocumentVersion:
    """Create a new version row. If status is ACTIVE, immediately archive
    the current active version and repoint the document -- used for
    auto-applied edits (image embeds). If status is PROPOSED, the version
    sits unlinked from doc.active_version_id until an explicit approve."""
    version = models.DocumentVersion(
        document_id=doc.id,
        version_number=_next_version_number(session, doc.id),
        content_html=new_content_html,
        content_text=chunking.normalize_text(new_content_html),
        status=status,
        change_summary=change_summary,
        created_by=created_by,
        pending_job_id=pending_job_id,
        pending_change_id=pending_change_id,
    )
    session.add(version)
    session.commit()
    session.refresh(version)

    if status == models.DocumentVersionStatus.ACTIVE:
        old_active = _active_version(session, doc)
        if old_active is not None and old_active.id != version.id:
            old_active.status = models.DocumentVersionStatus.ARCHIVED
            session.add(old_active)
        doc.active_version_id = version.id
        doc.updated_at = _now()
        session.add(doc)
        session.commit()
        session.refresh(doc)
        _propagate_staleness(session, doc.id)

    return version


def _propagate_staleness(session: Session, document_id: str) -> int:
    """Whenever a document's active version changes, flip every inbound
    DocumentLink to STALE if its synced_version_number no longer matches
    the (new) active version number. Plain integer comparison -- see
    models.py's module docstring. Returns the number of links flagged."""
    doc = session.get(models.Document, document_id)
    if doc is None or not doc.active_version_id:
        return 0
    active = session.get(models.DocumentVersion, doc.active_version_id)
    if active is None:
        return 0

    inbound = session.exec(
        select(models.DocumentLink).where(models.DocumentLink.target_document_id == document_id)
    ).all()
    flagged = 0
    for link in inbound:
        link.last_checked_at = _now()
        if link.synced_version_number != active.version_number:
            if link.status != models.LinkStatus.STALE:
                flagged += 1
                _record_event(
                    session,
                    models.ChangeEventType.LINK_FLAGGED_STALE,
                    campaign_id=doc.campaign_id,
                    document_id=document_id,
                    link_id=link.id,
                    description=f"{doc.title} moved to v{active.version_number}; link now stale",
                )
            link.status = models.LinkStatus.STALE
        session.add(link)
    session.commit()
    return flagged


# -------------------------------------------------------------------------- #
# health
# -------------------------------------------------------------------------- #


@app.get("/health")
def health():
    return {"status": "ok"}


# -------------------------------------------------------------------------- #
# campaigns
# -------------------------------------------------------------------------- #


@app.post("/campaigns")
def create_campaign(body: CampaignCreate, session: Session = Depends(db.get_session)):
    """Creates an EMPTY campaign -- no documents, no seed content. Everything
    from here is created or imported by the user."""
    c = models.Campaign(name=body.name, description=body.description, genre=body.genre, setting=body.setting)
    session.add(c)
    session.commit()
    session.refresh(c)
    _record_event(session, models.ChangeEventType.CAMPAIGN_CREATED, campaign_id=c.id, description=f"Campaign {c.name!r} created")
    return _campaign_out(c)


@app.get("/campaigns")
def list_campaigns(session: Session = Depends(db.get_session)):
    """
    NOTE: document_count/character_count were previously missing entirely
    from this list -- _campaign_out() never carried them, and only the
    single-campaign detail endpoint (GET /campaigns/{id}) computed them.
    The homepage campaign-card grid reads c.document_count/c.character_count
    off THIS endpoint's response, so every card silently showed "0
    documents · 0 characters" regardless of actual content. Fixed by
    computing the same counts here, in two bulk queries (not one query per
    campaign) so this stays cheap as the campaign list grows.
    """
    campaigns = session.exec(select(models.Campaign).order_by(models.Campaign.created_at.desc())).all()
    campaign_ids = [c.id for c in campaigns]

    doc_counts: dict[str, int] = {}
    char_counts: dict[str, int] = {}
    if campaign_ids:
        for d in session.exec(select(models.Document).where(models.Document.campaign_id.in_(campaign_ids))).all():
            doc_counts[d.campaign_id] = doc_counts.get(d.campaign_id, 0) + 1
        for ch in session.exec(select(models.Character).where(models.Character.campaign_id.in_(campaign_ids))).all():
            char_counts[ch.campaign_id] = char_counts.get(ch.campaign_id, 0) + 1

    out = []
    for c in campaigns:
        row = _campaign_out(c)
        row["document_count"] = doc_counts.get(c.id, 0)
        row["character_count"] = char_counts.get(c.id, 0)
        out.append(row)
    return out


@app.patch("/campaigns/{campaign_id}")
def patch_campaign(campaign_id: str, body: CampaignPatch, session: Session = Depends(db.get_session)):
    c = _get_campaign(session, campaign_id)
    if body.name is not None and body.name.strip():
        c.name = body.name.strip()
    if body.description is not None:
        c.description = body.description
    if body.genre is not None:
        c.genre = body.genre
    if body.setting is not None:
        c.setting = body.setting
    c.updated_at = _now()
    session.add(c)
    session.commit()
    session.refresh(c)
    _record_event(session, models.ChangeEventType.CAMPAIGN_UPDATED, campaign_id=c.id, description="Campaign details updated")
    return _campaign_out(c)


@app.delete("/campaigns/{campaign_id}")
def delete_campaign(campaign_id: str, session: Session = Depends(db.get_session)):
    """
    Deletes a campaign and everything under it. Reuses delete_document()'s
    cascade (versions, links, entity rows, entity-scoped illustrations,
    document-scoped chat) for every document in the campaign, then cleans up
    what's left at the campaign level: the campaign-level chat (e.g. the
    Campaign Assistant thread, which has document_id=None so the per-document
    cascade above never touches it), any illustrations that were generated
    but never embedded in a document, export audit rows, and change-log
    events. Irreversible -- there is no undo or trash/archive state.
    """
    campaign = _get_campaign(session, campaign_id)
    campaign_name = campaign.name

    doc_ids = [
        d.id for d in session.exec(select(models.Document).where(models.Document.campaign_id == campaign_id)).all()
    ]
    for doc_id in doc_ids:
        delete_document(doc_id, session)

    for cs in session.exec(select(models.ChatSession).where(models.ChatSession.campaign_id == campaign_id)).all():
        for m in session.exec(select(models.ChatMessage).where(models.ChatMessage.chat_session_id == cs.id)).all():
            session.delete(m)
        session.delete(cs)

    for i in session.exec(select(models.Illustration).where(models.Illustration.campaign_id == campaign_id)).all():
        session.delete(i)

    for e in session.exec(select(models.Export).where(models.Export.campaign_id == campaign_id)).all():
        session.delete(e)

    for ev in session.exec(select(models.ChangeEvent).where(models.ChangeEvent.campaign_id == campaign_id)).all():
        session.delete(ev)

    # ChatSession/Illustration/Export/ChangeEvent have no relationship()
    # back to Campaign (unlike Document, which does, via
    # Campaign.documents/Document.campaign) -- without that, SQLAlchemy's
    # unit-of-work has no dependency info telling it these rows must be
    # deleted before the campaign row when both are queued in the same
    # flush, and can emit DELETE FROM campaign first, hitting a real FK
    # violation on Postgres. Flushing the cleanup deletes here forces them
    # to hit the DB before campaign's own delete is even queued.
    session.flush()

    session.delete(campaign)
    session.commit()
    return {"status": "deleted", "campaign_id": campaign_id, "campaign_name": campaign_name, "deleted_documents": len(doc_ids)}


_IMAGE_URL_KEYS = ("url", "image_url", "file_url", "public_url", "cdn_url", "src", "href")


def _extract_image_url(upload: dict) -> str:
    """
    Pull the hosted image URL out of a client.upload_image_base64() response.

    SuperDocs' OpenAPI spec leaves this endpoint's response schema untyped
    (`{}`), so the exact key isn't guaranteed by the docs the way the request
    body is -- we already got burned once by guessing a request field name
    that turned out wrong (see superdocs_client.py). Rather than hardcode a
    second guess for the response and risk silently embedding an empty
    <img src="">  (exactly the "broken image + alt text" bug reported after
    the first fix), check the common key names first, then fall back to
    scanning every string value (including one level of nested dicts) for
    anything that looks like a URL. Raises loudly instead of returning ""
    so a shape change surfaces as a clear 502, not a silently broken image.
    """
    logger.info("SuperDocs images/upload-base64 raw response: %r", upload)

    if not isinstance(upload, dict):
        raise SuperDocsError(502, "images/upload-base64", f"unexpected response type: {type(upload).__name__}")

    for key in _IMAGE_URL_KEYS:
        val = upload.get(key)
        if isinstance(val, str) and val.startswith(("http://", "https://", "/")):
            logger.info("Resolved image URL via top-level key %r: %s", key, val)
            return val

    for val in upload.values():
        if isinstance(val, dict):
            for key in _IMAGE_URL_KEYS:
                nested = val.get(key)
                if isinstance(nested, str) and nested.startswith(("http://", "https://", "/")):
                    logger.info("Resolved image URL via nested key %r: %s", key, nested)
                    return nested

    for k, val in upload.items():
        if isinstance(val, str) and val.startswith(("http://", "https://")):
            logger.info("Resolved image URL via fallback scan of key %r: %s", k, val)
            return val

    logger.warning("Could not find an image URL anywhere in response: %r", upload)
    raise SuperDocsError(502, "images/upload-base64", f"couldn't find an image URL in response: {upload!r}")


@app.post("/campaigns/{campaign_id}/cover-image")
def upload_campaign_cover_image(
    campaign_id: str,
    file: UploadFile = File(...),
    client: SuperDocsClient = Depends(get_client),
    session: Session = Depends(db.get_session),
):
    campaign = _get_campaign(session, campaign_id)
    raw = file.file.read()
    if not raw:
        raise HTTPException(400, "uploaded file is empty")
    try:
        upload = client.upload_image_base64(filename=file.filename or f"{campaign_id}-cover.jpg", image_bytes=raw)
        image_url = _extract_image_url(upload)
    except SuperDocsError as e:
        raise HTTPException(502, f"SuperDocs image upload failed: {e}")

    campaign.cover_image = image_url
    campaign.updated_at = _now()
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    _record_event(session, models.ChangeEventType.CAMPAIGN_UPDATED, campaign_id=campaign_id, description="Cover image updated")
    return _campaign_out(campaign)


@app.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str, session: Session = Depends(db.get_session)):
    c = _get_campaign(session, campaign_id)
    docs = session.exec(select(models.Document).where(models.Document.campaign_id == campaign_id)).all()
    characters = session.exec(select(models.Character).where(models.Character.campaign_id == campaign_id)).all()
    npcs = session.exec(select(models.NPC).where(models.NPC.campaign_id == campaign_id)).all()
    locations = session.exec(select(models.Location).where(models.Location.campaign_id == campaign_id)).all()
    out = _campaign_out(c)
    out["document_count"] = len(docs)
    out["character_count"] = len(characters)
    out["npc_count"] = len(npcs)
    out["location_count"] = len(locations)
    return out


@app.get("/campaigns/{campaign_id}/documents")
def list_campaign_documents(
    campaign_id: str,
    q: str = Query("", description="search title/description"),
    doc_type: Optional[models.DocumentType] = Query(None),
    sort: str = Query("name", description="name | type | updated_at"),
    session: Session = Depends(db.get_session),
):
    _get_campaign(session, campaign_id)
    stmt = select(models.Document).where(models.Document.campaign_id == campaign_id)
    if doc_type is not None:
        stmt = stmt.where(models.Document.doc_type == doc_type)
    docs = session.exec(stmt).all()

    needle = q.strip().lower()
    if needle:
        docs = [d for d in docs if needle in d.title.lower() or needle in (d.description or "").lower()]

    if sort == "type":
        docs.sort(key=lambda d: (d.doc_type.value, d.title.lower()))
    elif sort == "updated_at":
        docs.sort(key=lambda d: d.updated_at, reverse=True)
    else:
        docs.sort(key=lambda d: d.title.lower())

    out = []
    for d in docs:
        active = _active_version(session, d)
        out.append(_doc_out(d, active_version=None) | {"active_version_number": active.version_number if active else None})
    return out


@app.get("/campaigns/{campaign_id}/characters")
def list_characters(campaign_id: str, session: Session = Depends(db.get_session)):
    _get_campaign(session, campaign_id)
    _ensure_entity_rows_for_type(session, campaign_id, models.DocumentType.CHARACTER)
    rows = session.exec(select(models.Character).where(models.Character.campaign_id == campaign_id)).all()
    return [_character_out(r) for r in rows]


@app.get("/campaigns/{campaign_id}/npcs")
def list_npcs(campaign_id: str, session: Session = Depends(db.get_session)):
    _get_campaign(session, campaign_id)
    _ensure_entity_rows_for_type(session, campaign_id, models.DocumentType.NPC)
    rows = session.exec(select(models.NPC).where(models.NPC.campaign_id == campaign_id)).all()
    return [_npc_out(r) for r in rows]


@app.get("/campaigns/{campaign_id}/locations")
def list_locations(campaign_id: str, session: Session = Depends(db.get_session)):
    _get_campaign(session, campaign_id)
    _ensure_entity_rows_for_type(session, campaign_id, models.DocumentType.LOCATION)
    rows = session.exec(select(models.Location).where(models.Location.campaign_id == campaign_id)).all()
    return [_location_out(r) for r in rows]


@app.get("/campaigns/{campaign_id}/links")
def list_campaign_links(campaign_id: str, session: Session = Depends(db.get_session)):
    _get_campaign(session, campaign_id)
    doc_ids = {d.id for d in session.exec(select(models.Document).where(models.Document.campaign_id == campaign_id)).all()}
    links = session.exec(select(models.DocumentLink)).all()
    return [_link_out(l) for l in links if l.source_document_id in doc_ids or l.target_document_id in doc_ids]


@app.post("/campaigns/{campaign_id}/relink-references")
def relink_campaign_references(campaign_id: str, session: Session = Depends(db.get_session)):
    """Bulk version of POST /documents/{id}/relink-references -- re-resolves
    every document in the campaign in one pass, so a resolver improvement
    (or a batch of newly-added documents) doesn't require opening and
    manually re-saving each document one at a time."""
    _get_campaign(session, campaign_id)
    docs = session.exec(select(models.Document).where(models.Document.campaign_id == campaign_id)).all()

    documents_updated = 0
    total_resolved = 0
    total_broken = 0
    for doc in docs:
        active = _active_version(session, doc)
        if active is None:
            continue
        rewritten_html, resolved_ids, broken_titles = _resolve_and_linkify_references(session, doc, active.content_html)
        if rewritten_html != active.content_html:
            _apply_active_version(
                session, doc, rewritten_html,
                status=models.DocumentVersionStatus.ACTIVE,
                change_summary="Re-linked [[references]]",
                created_by="system",
            )
            documents_updated += 1
        _sync_reference_links(session, doc, resolved_ids)
        total_resolved += len(resolved_ids)
        total_broken += len(broken_titles)

    if documents_updated:
        _record_event(
            session, models.ChangeEventType.DOCUMENT_SAVED,
            campaign_id=campaign_id,
            description=f"Re-linked references across {documents_updated} document(s)",
        )

    return {
        "documents_scanned": len(docs),
        "documents_updated": documents_updated,
        "total_resolved_references": total_resolved,
        "total_broken_references": total_broken,
    }


@app.get("/campaigns/{campaign_id}/events")
def list_campaign_events(campaign_id: str, session: Session = Depends(db.get_session)):
    _get_campaign(session, campaign_id)
    rows = session.exec(
        select(models.ChangeEvent).where(models.ChangeEvent.campaign_id == campaign_id).order_by(models.ChangeEvent.timestamp.desc())
    ).all()
    return [_event_out(r) for r in rows]


# -------------------------------------------------------------------------- #
# documents -- create (blank) + import (file upload, explicit type picker)
# -------------------------------------------------------------------------- #


@app.post("/campaigns/{campaign_id}/documents")
def create_document(campaign_id: str, body: DocumentCreate, client: SuperDocsClient = Depends(get_client), session: Session = Depends(db.get_session)):
    """Blank/starter document -- the user writes or pastes the content
    directly (or leaves it blank and fills it in later via chat)."""
    _get_campaign(session, campaign_id)
    content_html = body.content_html.strip() or f"<h1>{body.title}</h1><p></p>"
    doc = _create_document_with_version(
        session,
        client,
        campaign_id=campaign_id,
        doc_type=body.doc_type,
        title=body.title,
        description=body.description,
        content_html=content_html,
        filename=f"{body.title}.html",
        is_html_text=True,
        origin=models.DocumentOrigin.CREATED,
    )
    _record_event(session, models.ChangeEventType.DOCUMENT_CREATED, campaign_id=campaign_id, document_id=doc.id, description=f"Created {body.doc_type} {body.title!r}")
    return _doc_out(doc, active_version=_active_version(session, doc))


@app.post("/campaigns/{campaign_id}/documents/import")
def import_document(
    campaign_id: str,
    doc_type: models.DocumentType = Form(...),
    title: str = Form(""),
    description: str = Form(""),
    file: UploadFile = File(...),
    client: SuperDocsClient = Depends(get_client),
    session: Session = Depends(db.get_session),
):
    """
    File import IS supported, but there is no automatic classification --
    the caller must say what the file is (doc_type) at upload time, per the
    spec ("IMPORT DOCUMENT -> What is this?"). SuperDocs' own upload
    endpoint handles the actual format conversion (docx/pdf/txt/html all
    accepted); we just pass the raw bytes through with is_html_text=False.
    """
    _get_campaign(session, campaign_id)
    raw = file.file.read()
    if not raw:
        raise HTTPException(400, "uploaded file is empty")
    resolved_title = title.strip() or (file.filename or "Imported document").rsplit(".", 1)[0]
    doc = _create_document_with_version(
        session,
        client,
        campaign_id=campaign_id,
        doc_type=doc_type,
        title=resolved_title,
        description=description,
        content_html=raw,
        filename=file.filename or f"{resolved_title}.txt",
        is_html_text=False,
        origin=models.DocumentOrigin.IMPORTED,
    )
    _record_event(session, models.ChangeEventType.DOCUMENT_IMPORTED, campaign_id=campaign_id, document_id=doc.id, description=f"Imported {doc_type} from {file.filename!r}")
    return _doc_out(doc, active_version=_active_version(session, doc))


_ENTITY_TABLE_BY_DOC_TYPE = {
    models.DocumentType.CHARACTER: (models.Character, "character"),
    models.DocumentType.NPC: (models.NPC, "npc"),
    models.DocumentType.LOCATION: (models.Location, "location"),
}


def _ensure_entity_rows_for_type(session: Session, campaign_id: str, doc_type: models.DocumentType) -> None:
    """
    Backfill: most documents in this app are created via the generic
    create/import path (POST /campaigns/{id}/documents or .../documents/
    import -- this covers every uploaded DOCX and every "New document"
    click), which only ever writes a Document + DocumentVersion row. Only
    the dedicated POST /campaigns/{id}/characters|npcs|locations endpoints
    also create the matching Character/NPC/Location row.

    That split means a document titled "Blackspire Keep" with doc_type
    "location", imported the normal way, has NO backing Location row --
    which makes it invisible to the Characters/NPCs/Locations tabs (they
    list from those tables, not from Document) and to the illustration
    system (Illustration rows are keyed by entity_id, not document_id, so
    there's nothing to attach a picture to). This backfills the missing
    row from the document's own title, lazily and idempotently, so every
    character/npc/location-typed document behaves the same regardless of
    which endpoint created it.
    """
    table = _ENTITY_TABLE_BY_DOC_TYPE.get(doc_type)
    if table is None:
        return
    model_cls, _ = table
    docs = session.exec(
        select(models.Document).where(models.Document.campaign_id == campaign_id, models.Document.doc_type == doc_type)
    ).all()
    if not docs:
        return
    existing_doc_ids = {
        row.document_id for row in session.exec(select(model_cls).where(model_cls.campaign_id == campaign_id)).all()
    }
    created_any = False
    for d in docs:
        if d.id not in existing_doc_ids:
            session.add(model_cls(campaign_id=campaign_id, document_id=d.id, name=d.title))
            created_any = True
    if created_any:
        session.commit()


def _ensure_all_entity_rows(session: Session, campaign_id: str) -> None:
    for dt in _ENTITY_TABLE_BY_DOC_TYPE:
        _ensure_entity_rows_for_type(session, campaign_id, dt)


def _document_entity_info(session: Session, doc: models.Document) -> tuple[str | None, str | None, str | None]:
    """
    For a Character/NPC/Location document, look up its backing entity row
    (1:1 via entity.document_id) and return (entity_type, entity_id,
    image_url) -- lets the document detail page offer an inline "Add
    Illustration" action without a separate lookup call, since Illustration
    rows are keyed by entity_id, not document_id. Returns (None, None, None)
    for document types with no backing entity (Campaign Bible, Session Log,
    Other). Call _ensure_entity_rows_for_type first if the row might not
    exist yet (see that function's docstring).
    """
    table = _ENTITY_TABLE_BY_DOC_TYPE.get(doc.doc_type)
    if table is None:
        return None, None, None
    model_cls, type_str = table
    row = session.exec(select(model_cls).where(model_cls.document_id == doc.id)).first()
    if row is None:
        return None, None, None
    return type_str, row.id, row.image_url


@app.get("/documents/{document_id}")
def get_document_detail(document_id: str, session: Session = Depends(db.get_session)):
    d = _get_document(session, document_id)
    active = _active_version(session, d)
    out = _doc_out(d, active_version=active)
    broken: list[str] = []
    if active is not None:
        other_docs = session.exec(
            select(models.Document).where(models.Document.campaign_id == d.campaign_id, models.Document.id != d.id)
        ).all()
        for m in _REFERENCE_PATTERN.finditer(active.content_html):
            ref_title = m.group(1).strip()
            if _resolve_reference(session, ref_title, other_docs) is None and ref_title not in broken:
                broken.append(ref_title)
    out["broken_references"] = broken
    _ensure_entity_rows_for_type(session, d.campaign_id, d.doc_type)
    entity_type, entity_id, entity_image_url = _document_entity_info(session, d)
    out["entity_type"] = entity_type
    out["entity_id"] = entity_id
    out["entity_image_url"] = entity_image_url
    return out


@app.post("/documents/{document_id}/relink-references")
def relink_document_references(document_id: str, session: Session = Depends(db.get_session)):
    """
    Re-runs [[Reference]] resolution against the document's CURRENT active
    content and, if the result differs, writes it as a new active version.

    Why this needs to exist as its own action rather than happening
    automatically: resolution only ever runs at the moment content is
    written (create, manual save, chat-approval). A document written
    before a resolver improvement (e.g. teaching it to also match an
    internal "Document ID" table field) keeps its OLD rendered HTML
    forever -- the "N broken references" count you see elsewhere is a
    live re-scan and will correctly drop, but the stored content itself
    still shows plain/broken-styled text, not clickable links, until
    something rewrites it. This is that "something": call it on demand
    whenever resolution logic has improved and existing documents should
    pick up the newly-possible links.
    """
    doc = _get_document(session, document_id)
    active = _active_version(session, doc)
    if active is None:
        raise HTTPException(409, "document has no active version yet")

    rewritten_html, resolved_ids, broken_titles = _resolve_and_linkify_references(session, doc, active.content_html)
    changed = rewritten_html != active.content_html

    if changed:
        version = _apply_active_version(
            session, doc, rewritten_html,
            status=models.DocumentVersionStatus.ACTIVE,
            change_summary="Re-linked [[references]]",
            created_by="system",
        )
        _record_event(
            session, models.ChangeEventType.DOCUMENT_SAVED,
            campaign_id=doc.campaign_id, document_id=doc.id,
            description=f"Re-linked references ({len(resolved_ids)} resolved)",
        )
    else:
        version = active

    _sync_reference_links(session, doc, resolved_ids)
    return {
        "document": _doc_out(doc, active_version=version),
        "changed": changed,
        "resolved_reference_count": len(resolved_ids),
        "broken_references": broken_titles,
    }


@app.patch("/documents/{document_id}")
def patch_document(document_id: str, body: DocumentPatch, session: Session = Depends(db.get_session)):
    doc = _get_document(session, document_id)
    changes = []
    if body.title is not None and body.title.strip() and body.title.strip() != doc.title:
        changes.append(f"title {doc.title!r} -> {body.title.strip()!r}")
        doc.title = body.title.strip()
    if body.description is not None and body.description != doc.description:
        doc.description = body.description
    if body.doc_type is not None and body.doc_type != doc.doc_type:
        changes.append(f"type {doc.doc_type} -> {body.doc_type}")
        doc.doc_type = body.doc_type
    doc.updated_at = _now()
    session.add(doc)
    session.commit()
    session.refresh(doc)
    if changes:
        _record_event(
            session, models.ChangeEventType.DOCUMENT_RENAMED,
            campaign_id=doc.campaign_id, document_id=doc.id, description="; ".join(changes),
        )
    return _doc_out(doc, active_version=_active_version(session, doc))


def _detach_link_events(session: Session, link_id: str) -> None:
    """
    A DocumentLink can't just be deleted outright: every link creation (and
    every staleness flip/resync) records a ChangeEvent row with link_id set
    (see LINK_CREATED/LINK_FLAGGED_STALE/LINK_RESYNCED), and that column is a
    real foreign key to documentlink.id. On real Postgres (Render), deleting
    a link that still has a ChangeEvent pointing at it raises a
    ForeignKeyViolation -- this was never caught by the test suite because
    the in-memory SQLite fixture doesn't enforce foreign keys by default.
    Null out link_id on those events (rather than deleting them) so the
    change-log audit trail keeps its history even after the link itself is
    gone -- same "preserve the audit row, detach the dangling reference"
    pattern delete_document() already uses for embedded illustrations.
    """
    for ev in session.exec(select(models.ChangeEvent).where(models.ChangeEvent.link_id == link_id)).all():
        ev.link_id = None
        session.add(ev)


def _detach_document_events(session: Session, document_id: str) -> None:
    """Same problem as _detach_link_events(), one level up: DOCUMENT_CREATED/
    IMPORTED/SAVED/etc events record document_id, also a real foreign key.
    Deleting the document itself hits the same FK violation unless these are
    detached first."""
    for ev in session.exec(select(models.ChangeEvent).where(models.ChangeEvent.document_id == document_id)).all():
        ev.document_id = None
        session.add(ev)


@app.delete("/documents/{document_id}")
def delete_document(document_id: str, session: Session = Depends(db.get_session)):
    doc = _get_document(session, document_id)
    campaign_id = doc.campaign_id
    title = doc.title

    for v in session.exec(select(models.DocumentVersion).where(models.DocumentVersion.document_id == document_id)).all():
        session.delete(v)

    for l in session.exec(
        select(models.DocumentLink).where(
            (models.DocumentLink.source_document_id == document_id) | (models.DocumentLink.target_document_id == document_id)
        )
    ).all():
        _detach_link_events(session, l.id)
        session.delete(l)

    chat_session = session.exec(select(models.ChatSession).where(models.ChatSession.document_id == document_id)).first()
    if chat_session is not None:
        for m in session.exec(select(models.ChatMessage).where(models.ChatMessage.chat_session_id == chat_session.id)).all():
            session.delete(m)
        session.delete(chat_session)

    for i in session.exec(select(models.Illustration).where(models.Illustration.embedded_in_document_id == document_id)).all():
        i.embedded_in_document_id = None
        i.embedded = False
        session.add(i)

    entity_table = {
        models.DocumentType.CHARACTER: models.Character,
        models.DocumentType.NPC: models.NPC,
        models.DocumentType.LOCATION: models.Location,
    }.get(doc.doc_type)
    if entity_table is not None:
        row = session.exec(select(entity_table).where(entity_table.document_id == document_id)).first()
        if row is not None:
            for i in session.exec(select(models.Illustration).where(models.Illustration.entity_id == row.id)).all():
                session.delete(i)
            if doc.doc_type == models.DocumentType.LOCATION:
                for npc in session.exec(select(models.NPC).where(models.NPC.related_location_id == row.id)).all():
                    npc.related_location_id = None
                    session.add(npc)
            session.delete(row)

    _detach_document_events(session, document_id)
    session.delete(doc)
    session.commit()
    _record_event(session, models.ChangeEventType.DOCUMENT_DELETED, campaign_id=campaign_id, description=f"Deleted document {title!r}")
    return {"status": "deleted"}


@app.post("/documents/{document_id}/save")
def save_document(document_id: str, body: DocumentSaveIn, session: Session = Depends(db.get_session)):
    """
    Manual (non-AI) edit path: the frontend editor sends the full edited
    content_html directly and it becomes the new ACTIVE version immediately
    -- no SuperDocs chat/approval round-trip, since there's no AI-generated
    change here for a human to review. Runs the same [[reference]]
    resolution as document creation and chat-approval so manually written
    cross-links behave identically either way.
    """
    doc = _get_document(session, document_id)
    rewritten_html, resolved_ids, broken_titles = _resolve_and_linkify_references(session, doc, body.content_html)
    version = _apply_active_version(
        session, doc, rewritten_html,
        status=models.DocumentVersionStatus.ACTIVE,
        change_summary=(body.change_summary or "Manual edit")[:200],
        created_by="human",
    )
    _sync_reference_links(session, doc, resolved_ids)
    _record_event(
        session, models.ChangeEventType.DOCUMENT_SAVED,
        campaign_id=doc.campaign_id, document_id=doc.id,
        description=f"Manual save: {(body.change_summary or 'edited content')[:120]}",
    )
    return {
        "document": _doc_out(doc, active_version=version),
        "broken_references": broken_titles,
        "resolved_reference_count": len(resolved_ids),
    }


@app.get("/documents/{document_id}/versions")
def list_document_versions(document_id: str, session: Session = Depends(db.get_session)):
    _get_document(session, document_id)
    rows = session.exec(
        select(models.DocumentVersion).where(models.DocumentVersion.document_id == document_id).order_by(models.DocumentVersion.version_number.desc())
    ).all()
    return [_version_out(v, include_content=False) for v in rows]


@app.get("/documents/{document_id}/versions/{version_id}")
def get_document_version(document_id: str, version_id: str, session: Session = Depends(db.get_session)):
    v = session.get(models.DocumentVersion, version_id)
    if v is None or v.document_id != document_id:
        raise HTTPException(404, "version not found")
    return _version_out(v)


# -------------------------------------------------------------------------- #
# chat-driven editing (chat_async -> PROPOSED version -> approve/reject)
# -------------------------------------------------------------------------- #


@app.post("/documents/{document_id}/chat")
def chat_edit_document(document_id: str, body: ChatIn, client: SuperDocsClient = Depends(get_client), session: Session = Depends(db.get_session)):
    doc = _get_document(session, document_id)
    active = _active_version(session, doc)
    if active is None:
        raise HTTPException(409, "document has no active version yet")

    chat_session = session.exec(select(models.ChatSession).where(models.ChatSession.document_id == document_id)).first()
    if chat_session is None:
        chat_session = models.ChatSession(campaign_id=doc.campaign_id, document_id=document_id)
        session.add(chat_session)
        session.commit()
        session.refresh(chat_session)

    session.add(models.ChatMessage(chat_session_id=chat_session.id, role=models.ChatRole.USER, content=body.message))
    session.commit()

    try:
        job = client.chat_async(
            session_id=doc.superdocs_session_id,
            message=body.message,
            document_html=active.content_html,
            approval_mode="ask_every_time",
        )
        job = client.poll_job_until_done(job["job_id"])
    except SuperDocsError as e:
        assistant = models.ChatMessage(chat_session_id=chat_session.id, role=models.ChatRole.ASSISTANT, content=f"SuperDocs error: {e}")
        session.add(assistant)
        session.commit()
        raise HTTPException(502, f"SuperDocs chat failed: {e}")

    status = job.get("status")

    if status == "awaiting_approval":
        pending = SuperDocsClient.extract_pending_changes(job)
        candidate_html = active.content_html
        applied_count = 0
        for pc in pending:
            candidate_html, applied = _apply_pending_change(candidate_html, pc)
            if applied:
                applied_count += 1
        unapplied_count = len(pending) - applied_count

        if applied_count == 0:
            # Nothing could be merged into a previewable diff -- don't present a
            # "proposal" that's actually identical to the current document (the
            # Approve button would then silently do nothing visible). Reject the
            # changes on SuperDocs' side so that job doesn't stay stuck, and tell
            # the user plainly what happened.
            change_ids = [pc.change_id for pc in pending if pc.change_id]
            if change_ids and job.get("job_id"):
                try:
                    client.approve_changes_batch(
                        session_id=doc.superdocs_session_id,
                        job_id=job["job_id"],
                        decisions=[{"change_id": cid, "approved": False} for cid in change_ids],
                    )
                except SuperDocsError:
                    pass
            assistant = models.ChatMessage(
                chat_session_id=chat_session.id,
                role=models.ChatRole.ASSISTANT,
                content=(
                    f"SuperDocs proposed {len(pending)} change(s) but none could be merged into a preview "
                    "automatically, so nothing was applied. Try rephrasing the request (e.g. "
                    "\"add a new 'Summary' section at the end with...\") or use manual Edit instead."
                ),
            )
            session.add(assistant)
            session.commit()
            return {
                "status": "unapplied",
                "message": "Proposed change(s) could not be merged automatically.",
                "chat_message": _chat_message_out(assistant),
            }

        version = _apply_active_version(
            session,
            doc,
            candidate_html,
            status=models.DocumentVersionStatus.PROPOSED,
            change_summary=body.message[:200],
            created_by="ai",
            pending_job_id=job.get("job_id"),
            pending_change_id=",".join(pc.change_id for pc in pending),
        )
        note = "" if unapplied_count == 0 else f" ({unapplied_count} of {len(pending)} sub-change(s) could not be auto-merged and were skipped.)"
        assistant = models.ChatMessage(
            chat_session_id=chat_session.id,
            role=models.ChatRole.ASSISTANT,
            content=f"Proposed {applied_count} change(s) -- awaiting your approval.{note}",
            result_document_id=doc.id,
            result_version_id=version.id,
        )
        session.add(assistant)
        session.commit()
        _record_event(
            session,
            models.ChangeEventType.DOCUMENT_EDIT_PROPOSED,
            campaign_id=doc.campaign_id,
            document_id=doc.id,
            description=f"Proposed edit: {body.message[:120]}",
        )
        return {
            "status": "awaiting_approval",
            "version": _version_out(version),
            "pending_change_count": len(pending),
            "chat_message": _chat_message_out(assistant),
        }

    if status == "completed":
        assistant = models.ChatMessage(chat_session_id=chat_session.id, role=models.ChatRole.ASSISTANT, content="No changes were proposed for that request.")
        session.add(assistant)
        session.commit()
        return {"status": "completed", "message": "No changes proposed.", "chat_message": _chat_message_out(assistant)}

    assistant = models.ChatMessage(chat_session_id=chat_session.id, role=models.ChatRole.ASSISTANT, content=f"Edit did not complete (status: {status}).")
    session.add(assistant)
    session.commit()
    raise HTTPException(502, f"SuperDocs job ended with status={status}")


@app.get("/documents/{document_id}/chat/messages")
def list_chat_messages(document_id: str, session: Session = Depends(db.get_session)):
    _get_document(session, document_id)
    chat_session = session.exec(select(models.ChatSession).where(models.ChatSession.document_id == document_id)).first()
    if chat_session is None:
        return []
    rows = session.exec(
        select(models.ChatMessage).where(models.ChatMessage.chat_session_id == chat_session.id).order_by(models.ChatMessage.created_at)
    ).all()
    return [_chat_message_out(m) for m in rows]


_ASSISTANT_TYPE_HINTS: list[tuple[str, models.DocumentType]] = [
    ("npc", models.DocumentType.NPC),
    ("session", models.DocumentType.SESSION_LOG),
    ("character sheet", models.DocumentType.CHARACTER),
    ("character", models.DocumentType.CHARACTER),
    ("location", models.DocumentType.LOCATION),
    ("place", models.DocumentType.LOCATION),
]


def _assistant_suggest_doc_type(message: str) -> models.DocumentType:
    lower = message.lower()
    for kw, dt in _ASSISTANT_TYPE_HINTS:
        if kw in lower:
            return dt
    return models.DocumentType.OTHER


def _assistant_suggest_title(message: str, content_html: str) -> str:
    """Prefer the first heading in the generated content (the AI's own
    title for what it wrote); fall back to quoted text in the prompt, then
    a truncated version of the prompt itself."""
    headings = _heading_entries(_ensure_heading_anchors(content_html))
    if headings:
        return headings[0][1]
    quoted = re.search(r'"([^"]{3,80})"', message)
    if quoted:
        return quoted.group(1)
    words = re.sub(r"[^\w\s]", "", message).split()
    return " ".join(words[:6]).title() or "Untitled Draft"


def _get_or_create_assistant_session(session: Session, campaign_id: str) -> models.ChatSession:
    """The campaign-level assistant shares one ChatSession per campaign
    (document_id=None -- see the ChatSession model docstring, which was
    already designed for this, just never wired up to an endpoint)."""
    chat_session = session.exec(
        select(models.ChatSession).where(
            models.ChatSession.campaign_id == campaign_id, models.ChatSession.document_id.is_(None)
        )
    ).first()
    if chat_session is None:
        chat_session = models.ChatSession(campaign_id=campaign_id, document_id=None)
        session.add(chat_session)
        session.commit()
        session.refresh(chat_session)
    return chat_session


@app.get("/campaigns/{campaign_id}/assistant/messages")
def list_assistant_messages(campaign_id: str, session: Session = Depends(db.get_session)):
    _get_campaign(session, campaign_id)
    chat_session = session.exec(
        select(models.ChatSession).where(
            models.ChatSession.campaign_id == campaign_id, models.ChatSession.document_id.is_(None)
        )
    ).first()
    if chat_session is None:
        return []
    rows = session.exec(
        select(models.ChatMessage).where(models.ChatMessage.chat_session_id == chat_session.id).order_by(models.ChatMessage.created_at)
    ).all()
    return [_chat_message_out(m) for m in rows]


@app.post("/campaigns/{campaign_id}/assistant")
def campaign_assistant(
    campaign_id: str, body: ChatIn, client: SuperDocsClient = Depends(get_client), session: Session = Depends(db.get_session)
):
    """
    Campaign-level "Campaign Assistant": free-text prompt in, generated
    document HTML out -- e.g. "Create an NPC who serves Lord Kael" or
    "Summarize Session 3". Unlike the per-document chat-edit flow, there's
    no existing document to anchor the edit to, so this bootstraps a
    throwaway SuperDocs session with blank content and asks for content
    generated from scratch.

    Deliberately returns a DRAFT only -- nothing is saved to the campaign.
    The GM reviews it and explicitly saves it via the normal
    POST /campaigns/{id}/documents (create) call with the returned
    content_html, same as creating any other document. This keeps
    "AI writes it" and "GM approves what enters the campaign" as two
    distinct, explicit steps rather than silently growing the campaign.
    """
    campaign = _get_campaign(session, campaign_id)
    chat_session = _get_or_create_assistant_session(session, campaign_id)
    session.add(models.ChatMessage(chat_session_id=chat_session.id, role=models.ChatRole.USER, content=body.message))
    session.commit()

    sd_session_id = _fresh_session_id(campaign_id)
    try:
        client.upload_document_base64(
            filename="assistant-draft.html", html_or_bytes="<p></p>", session_id=sd_session_id, return_html=False, is_html_text=True
        )
        resp = client.chat(session_id=sd_session_id, message=body.message, document_html="<p></p>")
    except SuperDocsError as e:
        assistant_msg = models.ChatMessage(chat_session_id=chat_session.id, role=models.ChatRole.ASSISTANT, content=f"SuperDocs error: {e}")
        session.add(assistant_msg)
        session.commit()
        raise HTTPException(502, f"Campaign Assistant failed: {e}")

    content_html = ((resp.get("document_changes") or {}).get("updated_html") or "").strip()
    if not content_html:
        assistant_msg = models.ChatMessage(
            chat_session_id=chat_session.id, role=models.ChatRole.ASSISTANT,
            content="No content was generated for that request -- try rephrasing, e.g. \"Create an NPC named ...\".",
        )
        session.add(assistant_msg)
        session.commit()
        return {
            "content_html": "",
            "suggested_title": "",
            "suggested_doc_type": "other",
            "chat_message": _chat_message_out(assistant_msg),
        }

    suggested_type = _assistant_suggest_doc_type(body.message)
    suggested_title = _assistant_suggest_title(body.message, content_html)

    assistant_msg = models.ChatMessage(
        chat_session_id=chat_session.id, role=models.ChatRole.ASSISTANT,
        content=f'Drafted "{suggested_title}" ({DOC_TYPE_MANIFEST_LABELS.get(suggested_type, suggested_type)}) -- review and save it below if you want to keep it.',
    )
    session.add(assistant_msg)
    session.commit()
    _record_event(
        session, models.ChangeEventType.ASSISTANT_DRAFT_GENERATED,
        campaign_id=campaign_id, description=f"Campaign Assistant draft: {body.message[:120]}",
    )
    return {
        "content_html": content_html,
        "suggested_title": suggested_title,
        "suggested_doc_type": suggested_type,
        "chat_message": _chat_message_out(assistant_msg),
    }


@app.post("/documents/{document_id}/versions/{version_id}/approve")
def approve_version(document_id: str, version_id: str, client: SuperDocsClient = Depends(get_client), session: Session = Depends(db.get_session)):
    doc = _get_document(session, document_id)
    version = session.get(models.DocumentVersion, version_id)
    if version is None or version.document_id != document_id:
        raise HTTPException(404, "version not found")
    if version.status != models.DocumentVersionStatus.PROPOSED:
        raise HTTPException(409, f"version is {version.status}, not proposed")

    change_ids = [c for c in (version.pending_change_id or "").split(",") if c]
    if change_ids and version.pending_job_id:
        try:
            client.approve_changes_batch(
                session_id=doc.superdocs_session_id,
                job_id=version.pending_job_id,
                decisions=[{"change_id": cid, "approved": True} for cid in change_ids],
            )
        except SuperDocsError as e:
            raise HTTPException(502, f"SuperDocs approve failed: {e}")

    old_active = _active_version(session, doc)
    if old_active is not None:
        old_active.status = models.DocumentVersionStatus.ARCHIVED
        session.add(old_active)
    version.status = models.DocumentVersionStatus.ACTIVE
    version.pending_job_id = None
    version.pending_change_id = None
    session.add(version)
    doc.active_version_id = version.id
    doc.updated_at = _now()
    session.add(doc)
    session.commit()
    session.refresh(version)
    session.refresh(doc)

    # An AI-proposed edit can itself introduce or remove [[Reference]] text --
    # resolve it the same way a manual save or initial creation would.
    rewritten_html, resolved_ids, _broken = _resolve_and_linkify_references(session, doc, version.content_html)
    if rewritten_html != version.content_html:
        version.content_html = rewritten_html
        version.content_text = chunking.normalize_text(rewritten_html)
        session.add(version)
        session.commit()
        session.refresh(version)
    _sync_reference_links(session, doc, resolved_ids)

    flagged = _propagate_staleness(session, doc.id)
    _record_event(
        session,
        models.ChangeEventType.DOCUMENT_EDIT_APPROVED,
        campaign_id=doc.campaign_id,
        document_id=doc.id,
        description=f"Approved v{version.version_number}: {version.change_summary}",
        approved=True,
    )
    return {"document": _doc_out(doc, active_version=version), "links_flagged_stale": flagged}


@app.post("/documents/{document_id}/versions/{version_id}/reject")
def reject_version(document_id: str, version_id: str, client: SuperDocsClient = Depends(get_client), session: Session = Depends(db.get_session)):
    doc = _get_document(session, document_id)
    version = session.get(models.DocumentVersion, version_id)
    if version is None or version.document_id != document_id:
        raise HTTPException(404, "version not found")
    if version.status != models.DocumentVersionStatus.PROPOSED:
        raise HTTPException(409, f"version is {version.status}, not proposed")

    change_ids = [c for c in (version.pending_change_id or "").split(",") if c]
    if change_ids and version.pending_job_id:
        try:
            client.approve_changes_batch(
                session_id=doc.superdocs_session_id,
                job_id=version.pending_job_id,
                decisions=[{"change_id": cid, "approved": False} for cid in change_ids],
            )
        except SuperDocsError:
            pass  # best-effort -- we still discard our own proposed version below

    summary = version.change_summary
    session.delete(version)
    session.commit()
    _record_event(
        session,
        models.ChangeEventType.DOCUMENT_EDIT_REJECTED,
        campaign_id=doc.campaign_id,
        document_id=doc.id,
        description=f"Rejected proposed edit: {summary}",
        approved=False,
    )
    return {"status": "rejected"}


# -------------------------------------------------------------------------- #
# characters / npcs / locations -- entity + backing document in one call
# -------------------------------------------------------------------------- #


@app.post("/campaigns/{campaign_id}/characters")
def create_character(campaign_id: str, body: EntityCreate, client: SuperDocsClient = Depends(get_client), session: Session = Depends(db.get_session)):
    _get_campaign(session, campaign_id)
    content_html = body.content_html.strip() or f"<h1>{body.name}</h1><p>{body.description}</p>"
    doc = _create_document_with_version(
        session, client,
        campaign_id=campaign_id, doc_type=models.DocumentType.CHARACTER, title=body.name,
        description=body.description, content_html=content_html, filename=f"{body.name}.html",
        is_html_text=True, origin=models.DocumentOrigin.CREATED,
    )
    row = models.Character(campaign_id=campaign_id, document_id=doc.id, name=body.name, race=body.race, char_class=body.char_class, level=body.level)
    session.add(row)
    session.commit()
    session.refresh(row)
    _record_event(session, models.ChangeEventType.DOCUMENT_CREATED, campaign_id=campaign_id, document_id=doc.id, description=f"Created character {body.name!r}")
    return {"character": _character_out(row), "document": _doc_out(doc, active_version=_active_version(session, doc))}


@app.post("/campaigns/{campaign_id}/npcs")
def create_npc(campaign_id: str, body: EntityCreate, client: SuperDocsClient = Depends(get_client), session: Session = Depends(db.get_session)):
    _get_campaign(session, campaign_id)
    content_html = body.content_html.strip() or f"<h1>{body.name}</h1><p>{body.description}</p>"
    doc = _create_document_with_version(
        session, client,
        campaign_id=campaign_id, doc_type=models.DocumentType.NPC, title=body.name,
        description=body.description, content_html=content_html, filename=f"{body.name}.html",
        is_html_text=True, origin=models.DocumentOrigin.CREATED,
    )
    row = models.NPC(campaign_id=campaign_id, document_id=doc.id, name=body.name, role=body.role, related_location_id=body.related_location_id)
    session.add(row)
    session.commit()
    session.refresh(row)
    _record_event(session, models.ChangeEventType.DOCUMENT_CREATED, campaign_id=campaign_id, document_id=doc.id, description=f"Created NPC {body.name!r}")
    return {"npc": _npc_out(row), "document": _doc_out(doc, active_version=_active_version(session, doc))}


@app.post("/campaigns/{campaign_id}/locations")
def create_location(campaign_id: str, body: EntityCreate, client: SuperDocsClient = Depends(get_client), session: Session = Depends(db.get_session)):
    _get_campaign(session, campaign_id)
    content_html = body.content_html.strip() or f"<h1>{body.name}</h1><p>{body.description}</p>"
    doc = _create_document_with_version(
        session, client,
        campaign_id=campaign_id, doc_type=models.DocumentType.LOCATION, title=body.name,
        description=body.description, content_html=content_html, filename=f"{body.name}.html",
        is_html_text=True, origin=models.DocumentOrigin.CREATED,
    )
    row = models.Location(campaign_id=campaign_id, document_id=doc.id, name=body.name)
    session.add(row)
    session.commit()
    session.refresh(row)
    _record_event(session, models.ChangeEventType.DOCUMENT_CREATED, campaign_id=campaign_id, document_id=doc.id, description=f"Created location {body.name!r}")
    return {"location": _location_out(row), "document": _doc_out(doc, active_version=_active_version(session, doc))}


# -------------------------------------------------------------------------- #
# links -- user-defined edges with version-number staleness tracking
# -------------------------------------------------------------------------- #


@app.post("/links")
def create_link(body: LinkCreate, session: Session = Depends(db.get_session)):
    source = _get_document(session, body.source_document_id)
    target = _get_document(session, body.target_document_id)
    target_active = _active_version(session, target)
    if target_active is None:
        raise HTTPException(409, "target document has no active version yet")

    link = models.DocumentLink(
        source_document_id=source.id,
        target_document_id=target.id,
        relationship_type=body.relationship_type,
        note=body.note,
        synced_version_number=target_active.version_number,
        status=models.LinkStatus.SYNCED,
    )
    session.add(link)
    session.commit()
    session.refresh(link)
    _record_event(
        session,
        models.ChangeEventType.LINK_CREATED,
        campaign_id=source.campaign_id,
        document_id=source.id,
        link_id=link.id,
        description=f"{source.title!r} {body.relationship_type} {target.title!r}",
    )
    return _link_out(link)


@app.get("/links/{link_id}")
def get_link(link_id: str, session: Session = Depends(db.get_session)):
    link = session.get(models.DocumentLink, link_id)
    if link is None:
        raise HTTPException(404, "link not found")
    return _link_out(link)


@app.post("/links/{link_id}/resync")
def resync_link(link_id: str, session: Session = Depends(db.get_session)):
    link = session.get(models.DocumentLink, link_id)
    if link is None:
        raise HTTPException(404, "link not found")
    target = _get_document(session, link.target_document_id)
    target_active = _active_version(session, target)
    if target_active is None:
        raise HTTPException(409, "target document has no active version")

    link.synced_version_number = target_active.version_number
    link.status = models.LinkStatus.SYNCED
    link.last_checked_at = _now()
    session.add(link)
    session.commit()
    session.refresh(link)
    _record_event(
        session,
        models.ChangeEventType.LINK_RESYNCED,
        campaign_id=target.campaign_id,
        document_id=target.id,
        link_id=link.id,
        description=f"Link resynced to v{target_active.version_number}",
    )
    return _link_out(link)


@app.delete("/links/{link_id}")
def delete_link(link_id: str, session: Session = Depends(db.get_session)):
    link = session.get(models.DocumentLink, link_id)
    if link is None:
        raise HTTPException(404, "link not found")
    _detach_link_events(session, link_id)
    session.delete(link)
    session.commit()
    return {"status": "deleted"}


# -------------------------------------------------------------------------- #
# illustrations -- Pollinations generation + optional embed
# -------------------------------------------------------------------------- #


def _insert_image_after_heading(html: str, img_tag: str) -> str:
    """
    Deterministically inserts img_tag right after the document's first
    heading (h1/h2/h3), or prepends it if no heading is found.

    generate_illustration used to ask SuperDocs' own chat AI to do this
    insertion ("Insert this image right after the main heading..."). For
    short/sparse documents (exactly what a freshly-created Character/NPC/
    Location sheet is, since the simplified creation forms only ask for a
    Name) that AI edit was observed replacing the real heading text with a
    literal "Please fill: Main Heading" placeholder -- the AI apparently
    treating a short document as an incomplete template rather than doing
    the surgical insert asked for. upload_illustration never had this
    problem because it never went through an AI edit at all: it just
    appends the <img> tag to the existing HTML directly. This mirrors that
    approach for generate_illustration too, trading "AI figures out where
    the heading is" for a plain regex insert -- deterministic, and it can't
    rewrite content it never touches.
    """
    match = re.search(r"</h[123]>", html, flags=re.IGNORECASE)
    if match:
        insert_at = match.end()
        return html[:insert_at] + img_tag + html[insert_at:]
    return img_tag + html


def _entity_document_id(session: Session, entity_type: models.IllustrationEntityType, entity_id: str) -> tuple[str, str, str]:
    """Returns (campaign_id, document_id, name) for a Character/NPC/Location."""
    table = {
        models.IllustrationEntityType.CHARACTER: models.Character,
        models.IllustrationEntityType.NPC: models.NPC,
        models.IllustrationEntityType.LOCATION: models.Location,
    }[entity_type]
    row = session.get(table, entity_id)
    if row is None:
        raise HTTPException(404, f"{entity_type} {entity_id} not found")
    return row.campaign_id, row.document_id, row.name


@app.post("/illustrations")
def generate_illustration(body: IllustrationCreate, client: SuperDocsClient = Depends(get_client), session: Session = Depends(db.get_session)):
    campaign_id, document_id, entity_name = _entity_document_id(session, body.entity_type, body.entity_id)

    try:
        image_bytes, content_type = image_gen.generate_illustration(body.prompt, width=body.width, height=body.height, seed=body.seed)
    except image_gen.ImageGenError as e:
        raise HTTPException(502, f"image generation failed: {e}")

    ext = (content_type.split("/")[-1] or "jpg").split(";")[0]
    try:
        upload = client.upload_image_base64(filename=f"{body.entity_id}.{ext}", image_bytes=image_bytes)
        image_url = _extract_image_url(upload)
    except SuperDocsError as e:
        raise HTTPException(502, f"SuperDocs image upload failed: {e}")

    local_image_path = _save_local_illustration(image_bytes, ext)
    # Use for anything THIS app renders in a browser (embedded doc HTML via
    # dangerouslySetInnerHTML, the entity portrait, the gallery) -- the
    # SuperDocs URL has been observed 403'ing on a plain anonymous <img>
    # fetch, so it isn't safe to hand to a browser directly. It's still
    # stored as superdocs_image_url and is what actually gets sent in the
    # chat message below, since that's the reference SuperDocs' own session
    # needs; only the value written into the rendered HTML changes.
    embed_url = _local_image_url(local_image_path) or image_url

    illustration = models.Illustration(
        campaign_id=campaign_id,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        prompt=body.prompt,
        superdocs_image_url=image_url,
        local_image_path=local_image_path,
    )
    session.add(illustration)
    session.commit()
    session.refresh(illustration)

    doc = _get_document(session, document_id)

    if body.embed:
        active = _active_version(session, doc)
        if active is not None:
            img_tag = f'<img src="{embed_url}" alt="{entity_name}" style="max-width:100%;" />'
            updated_html = _insert_image_after_heading(active.content_html, img_tag)

            _apply_active_version(
                session, doc, updated_html,
                status=models.DocumentVersionStatus.ACTIVE,
                change_summary=f"Embedded illustration: {body.prompt[:100]}",
                created_by="system",
            )
            illustration.embedded = True
            illustration.embedded_in_document_id = doc.id
            session.add(illustration)
            # keep the entity's own image_url pointer in sync
            table = {
                models.IllustrationEntityType.CHARACTER: models.Character,
                models.IllustrationEntityType.NPC: models.NPC,
                models.IllustrationEntityType.LOCATION: models.Location,
            }[body.entity_type]
            entity_row = session.get(table, body.entity_id)
            if entity_row is not None:
                entity_row.image_url = embed_url
                session.add(entity_row)
            session.commit()
            session.refresh(illustration)

    _record_event(
        session,
        models.ChangeEventType.IMAGE_GENERATED,
        campaign_id=campaign_id,
        document_id=document_id,
        description=f"Generated illustration for {entity_name!r}: {body.prompt[:100]}",
    )
    return _illustration_out(illustration)


@app.post("/illustrations/upload")
def upload_illustration(
    entity_type: models.IllustrationEntityType = Form(...),
    entity_id: str = Form(...),
    prompt: str = Form(""),
    embed: bool = Form(True),
    file: UploadFile = File(...),
    client: SuperDocsClient = Depends(get_client),
    session: Session = Depends(db.get_session),
):
    """Manual counterpart to POST /illustrations: the user supplies their
    own image file instead of generating one via Pollinations."""
    campaign_id, document_id, entity_name = _entity_document_id(session, entity_type, entity_id)
    raw = file.file.read()
    if not raw:
        raise HTTPException(400, "uploaded file is empty")
    try:
        upload = client.upload_image_base64(filename=file.filename or f"{entity_id}.jpg", image_bytes=raw)
        image_url = _extract_image_url(upload)
    except SuperDocsError as e:
        raise HTTPException(502, f"SuperDocs image upload failed: {e}")

    upload_ext = (file.filename or "").rsplit(".", 1)[-1] if file.filename and "." in file.filename else "jpg"
    local_image_path = _save_local_illustration(raw, upload_ext)
    # see the matching comment in generate_illustration -- use our own
    # reliably-reachable copy for anything rendered in a browser here.
    embed_url = _local_image_url(local_image_path) or image_url

    illustration = models.Illustration(
        campaign_id=campaign_id,
        entity_type=entity_type,
        entity_id=entity_id,
        prompt=prompt or "(uploaded image)",
        provider="upload",
        model="",
        superdocs_image_url=image_url,
        local_image_path=local_image_path,
    )
    session.add(illustration)
    session.commit()
    session.refresh(illustration)

    doc = _get_document(session, document_id)
    if embed:
        active = _active_version(session, doc)
        if active is not None:
            new_html = active.content_html + f'\n<p><img src="{embed_url}" alt="{entity_name}" style="max-width:100%;" /></p>'
            _apply_active_version(
                session, doc, new_html,
                status=models.DocumentVersionStatus.ACTIVE,
                change_summary="Embedded uploaded illustration",
                created_by="human",
            )
            illustration.embedded = True
            illustration.embedded_in_document_id = doc.id
            session.add(illustration)
            table = {
                models.IllustrationEntityType.CHARACTER: models.Character,
                models.IllustrationEntityType.NPC: models.NPC,
                models.IllustrationEntityType.LOCATION: models.Location,
            }[entity_type]
            entity_row = session.get(table, entity_id)
            if entity_row is not None:
                entity_row.image_url = embed_url
                session.add(entity_row)
            session.commit()
            session.refresh(illustration)

    _record_event(
        session, models.ChangeEventType.IMAGE_UPLOADED,
        campaign_id=campaign_id, document_id=document_id,
        description=f"Uploaded illustration for {entity_name!r}",
    )
    return _illustration_out(illustration)


@app.get("/campaigns/{campaign_id}/illustrations")
def list_campaign_illustrations(campaign_id: str, session: Session = Depends(db.get_session)):
    _get_campaign(session, campaign_id)
    rows = session.exec(select(models.Illustration).where(models.Illustration.campaign_id == campaign_id)).all()
    return [_illustration_out(r) for r in rows]


# -------------------------------------------------------------------------- #
# export
# -------------------------------------------------------------------------- #


@app.get("/documents/{document_id}/export")
def export_document(document_id: str, format: str = Query("docx"), client: SuperDocsClient = Depends(get_client), session: Session = Depends(db.get_session)):
    if format not in _EXPORT_CONTENT_TYPES or format == "zip":
        raise HTTPException(400, f"unsupported single-document format: {format!r}")
    doc = _get_document(session, document_id)
    active = _active_version(session, doc)
    if active is None:
        raise HTTPException(409, "document has no active content to export")
    try:
        # Export straight from our own DB's active-version HTML (the true
        # source of truth, including any manual saves) rather than by
        # session_id, which only reflects whatever SuperDocs' own session
        # last saw -- a manual edit never round-trips through SuperDocs.
        content = client.export(html=active.content_html, fmt=format, filename=_safe_filename(doc.title, format))
    except SuperDocsError as e:
        raise HTTPException(502, f"export failed: {e}")
    fname = _safe_filename(doc.title, format)
    return Response(content=content, media_type=_EXPORT_CONTENT_TYPES[format], headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.get("/campaigns/{campaign_id}/export")
def export_campaign(campaign_id: str, format: str = Query("docx"), session: Session = Depends(db.get_session), client: SuperDocsClient = Depends(get_client)):
    """
    Bundles every document into one zip, grouped into subfolders by
    doc_type (Characters/, NPCs/, Locations/, Sessions/), plus a
    MANIFEST.txt listing every DocumentLink and Illustration so the export
    reads as a coherent, cross-referenced set rather than a pile of loose
    files.
    """
    campaign = _get_campaign(session, campaign_id)
    _ensure_all_entity_rows(session, campaign_id)
    docs = session.exec(select(models.Document).where(models.Document.campaign_id == campaign_id)).all()
    if not docs:
        raise HTTPException(409, "campaign has no documents to export")

    doc_ids = {d.id for d in docs}
    links = [l for l in session.exec(select(models.DocumentLink)).all() if l.source_document_id in doc_ids or l.target_document_id in doc_ids]
    illustrations = session.exec(select(models.Illustration).where(models.Illustration.campaign_id == campaign_id)).all()
    doc_by_id = {d.id: d for d in docs}

    _DOC_TYPE_ORDER = [
        models.DocumentType.CAMPAIGN_BIBLE,
        models.DocumentType.CHARACTER,
        models.DocumentType.NPC,
        models.DocumentType.LOCATION,
        models.DocumentType.SESSION_LOG,
        models.DocumentType.OTHER,
    ]
    grouped: dict[models.DocumentType, list[models.Document]] = defaultdict(list)
    for d in docs:
        grouped[d.doc_type].append(d)
    for dt in grouped:
        grouped[dt].sort(key=lambda d: d.title.lower())

    # broken/unresolved [[reference]] scan across every document's current
    # active content -- feeds both the manifest's cross-reference count and
    # (via _resolve_reference) benefits from the same section/entity-anchor
    # resolution used everywhere else.
    total_ref_count = 0
    unresolved_refs: list[str] = []
    for d in docs:
        active = _active_version(session, d)
        if active is None:
            continue
        other_docs = [x for x in docs if x.id != d.id]
        for m in _REFERENCE_PATTERN.finditer(active.content_html):
            total_ref_count += 1
            ref_title = m.group(1).strip()
            if _resolve_reference(session, ref_title, other_docs) is None:
                unresolved_refs.append(f"{d.title}: [[{ref_title}]]")
    resolved_ref_count = total_ref_count - len(unresolved_refs)

    # entity display names, for a friendlier Assets/ manifest listing than
    # the raw "character:<uuid>" the Illustration row alone carries.
    entity_name_by_id: dict[str, str] = {}
    for c in session.exec(select(models.Character).where(models.Character.campaign_id == campaign_id)).all():
        entity_name_by_id[c.id] = c.name
    for n in session.exec(select(models.NPC).where(models.NPC.campaign_id == campaign_id)).all():
        entity_name_by_id[n.id] = n.name
    for loc in session.exec(select(models.Location).where(models.Location.campaign_id == campaign_id)).all():
        entity_name_by_id[loc.id] = loc.name

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        index_lines_html = [f"<h1>{campaign.name} -- Campaign Pack</h1>"]
        if campaign.genre:
            index_lines_html.append(f"<p><b>Genre:</b> {campaign.genre}</p>")
        if campaign.description:
            index_lines_html.append(f"<p>{campaign.description}</p>")
        index_lines_html.append("<h2>Contents</h2><ul>")

        document_manifest_lines: list[str] = []
        for dt in _DOC_TYPE_ORDER:
            subfolder = _DOC_TYPE_SUBFOLDER.get(dt, "Other/")
            for idx, d in enumerate(grouped.get(dt, []), start=1):
                active = _active_version(session, d)
                if active is None:
                    continue
                try:
                    # html= exports our DB's active-version content directly
                    # (source of truth, includes manual saves) rather than
                    # relying on SuperDocs' own last-seen session state.
                    content = client.export(html=active.content_html, fmt=format, filename=_safe_filename(d.title, format))
                except SuperDocsError:
                    continue
                fname = _numbered_filename(idx, d.title, format)
                zf.writestr(subfolder + fname, content)
                index_lines_html.append(f"<li>{subfolder}{fname}</li>")
                document_manifest_lines.append(f"- {d.title} ({DOC_TYPE_MANIFEST_LABELS.get(dt, dt)})")
        index_lines_html.append("</ul>")

        try:
            readme_bytes = client.export(html="".join(index_lines_html), fmt="docx", filename="00_Campaign_Pack_Index_README.docx")
            zf.writestr("00_Campaign_Pack_Index_README.docx", readme_bytes)
        except SuperDocsError:
            import re as _re
            plain = _re.sub(r"<[^>]+>", "\n", "".join(index_lines_html))
            zf.writestr("00_Campaign_Pack_Index_README.txt", plain)

        # Assets/ -- actual image bytes, not just a manifest reference, so
        # e.g. Blackspire Keep's illustration ships inside the zip itself.
        #
        # Read from our own local copy (ILLUSTRATIONS_DIR / local_image_path)
        # first, not i.superdocs_image_url -- that's the storage.googleapis.com
        # link with the known GCS-ACL bug (see _save_local_illustration's
        # docstring): an anonymous GET against it 403s "AccessDenied" even
        # though the SuperDocs upload call that produced it succeeded. This
        # loop used to fetch superdocs_image_url directly and silently
        # `continue` past that 403 -- which is exactly why a campaign with a
        # real, embedded illustration could still export with an empty
        # Assets/ folder and no error anywhere. We already hold these bytes
        # on disk (every illustration row gets a local_image_path at
        # generation/upload time), so there's no reason to go back over the
        # network -- and no silent failure mode left for a build that has
        # one.
        asset_manifest_lines: list[str] = []
        seen_asset_names: set[str] = set()
        for i in illustrations:
            image_bytes: bytes | None = None
            ext = "png"
            if i.local_image_path:
                local_path = os.path.join(ILLUSTRATIONS_DIR, i.local_image_path)
                try:
                    with open(local_path, "rb") as f:
                        image_bytes = f.read()
                    ext = (i.local_image_path.rsplit(".", 1)[-1] or "png").lower()
                except OSError:
                    image_bytes = None
            if image_bytes is None and i.superdocs_image_url:
                # Fallback for any pre-local-hosting illustration row that
                # somehow has no local_image_path -- best effort only, since
                # this is the URL known to 403 on SuperDocs' end.
                try:
                    resp = requests.get(i.superdocs_image_url, timeout=20)
                    resp.raise_for_status()
                    image_bytes = resp.content
                    content_type = resp.headers.get("Content-Type", "")
                    ext = (content_type.split("/")[-1].split(";")[0] or "png") if content_type else "png"
                except Exception:
                    image_bytes = None
            if image_bytes is None:
                continue
            if ext not in ("png", "jpg", "jpeg", "webp", "gif"):
                ext = "png"
            entity_name = entity_name_by_id.get(i.entity_id, i.entity_id)
            base_name = _slugify(entity_name) + "-illustration"
            asset_name = f"{base_name}.{ext}"
            n = 2
            while asset_name in seen_asset_names:
                asset_name = f"{base_name}-{n}.{ext}"
                n += 1
            seen_asset_names.add(asset_name)
            zf.writestr(f"Assets/{asset_name}", image_bytes)
            asset_manifest_lines.append(f"- {asset_name} ({entity_name})")

        manifest_lines = [
            f"Campaign: {campaign.name}",
            "Export Version: 1.0",
            f"Exported: {_now().strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "Documents:",
        ]
        manifest_lines.extend(document_manifest_lines or ["  (none)"])
        manifest_lines.append("")
        manifest_lines.append("Assets:")
        manifest_lines.extend([f"  {line}" for line in asset_manifest_lines] or ["  (none)"])
        manifest_lines.append("")
        manifest_lines.append("Cross-references:")
        manifest_lines.append(f"  {resolved_ref_count} resolved")
        manifest_lines.append(f"  {len(unresolved_refs)} unresolved")
        if unresolved_refs:
            manifest_lines.append("")
            manifest_lines.append("  Unresolved:")
            manifest_lines.extend(f"    - {r}" for r in unresolved_refs)
        manifest_lines.append("")
        manifest_lines.append("Links (cross-document relationships):")
        for l in links:
            src = doc_by_id.get(l.source_document_id)
            tgt = doc_by_id.get(l.target_document_id)
            manifest_lines.append(
                f"  {src.title if src else l.source_document_id} --{l.relationship_type}--> "
                f"{tgt.title if tgt else l.target_document_id}  [{l.status}]"
            )
        zf.writestr("MANIFEST.txt", "\n".join(manifest_lines))

    buf.seek(0)
    export_row = models.Export(campaign_id=campaign_id, format=models.ExportFormat.ZIP, document_count=len(docs))
    session.add(export_row)
    session.commit()
    _record_event(session, models.ChangeEventType.EXPORT_CREATED, campaign_id=campaign_id, description=f"Exported {len(docs)} documents as zip")

    fname = _safe_filename(campaign.name, "zip")
    return Response(content=buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# -------------------------------------------------------------------------- #
# validator -- local-only, recomputes link staleness on demand
# -------------------------------------------------------------------------- #


@app.get("/campaigns/{campaign_id}/validate")
def validate_campaign(campaign_id: str, session: Session = Depends(db.get_session)):
    """
    Recomputes link staleness on demand (as before) and additionally builds
    the "Campaign Readiness" checklist from the spec: doc-type coverage
    (Bible / characters / NPCs / locations / session logs), illustration
    coverage per character/NPC/location, broken [[reference]] detection,
    and duplicate-title warnings within a doc_type. All previously-existing
    response fields are kept unchanged so the original CoherenceTab keeps
    working; new fields are additive.
    """
    campaign = _get_campaign(session, campaign_id)
    _ensure_all_entity_rows(session, campaign_id)
    docs = session.exec(select(models.Document).where(models.Document.campaign_id == campaign_id)).all()
    doc_ids = {d.id for d in docs}
    characters = session.exec(select(models.Character).where(models.Character.campaign_id == campaign_id)).all()
    npcs = session.exec(select(models.NPC).where(models.NPC.campaign_id == campaign_id)).all()
    locations = session.exec(select(models.Location).where(models.Location.campaign_id == campaign_id)).all()
    illustrations = session.exec(select(models.Illustration).where(models.Illustration.campaign_id == campaign_id)).all()
    illustrated_entity_ids = {i.entity_id for i in illustrations}

    missing_active = [d.title for d in docs if not d.active_version_id]

    links = [l for l in session.exec(select(models.DocumentLink)).all() if l.source_document_id in doc_ids]
    link_reports = []
    stale_count = 0
    for l in links:
        target = session.get(models.Document, l.target_document_id)
        if target is None or not target.active_version_id:
            continue
        active = session.get(models.DocumentVersion, target.active_version_id)
        current_number = active.version_number if active else None
        is_stale = current_number is not None and l.synced_version_number != current_number
        if is_stale and l.status != models.LinkStatus.STALE:
            l.status = models.LinkStatus.STALE
            session.add(l)
        elif not is_stale and l.status == models.LinkStatus.STALE:
            l.status = models.LinkStatus.SYNCED
            session.add(l)
        if is_stale:
            stale_count += 1
        link_reports.append({
            "link_id": l.id,
            "source_document_id": l.source_document_id,
            "target_document_id": l.target_document_id,
            "relationship_type": l.relationship_type,
            "synced_version_number": l.synced_version_number,
            "current_version_number": current_number,
            "stale": is_stale,
        })
    session.commit()

    # broken [[reference]] scan across every document's current active content
    broken_refs = []
    for d in docs:
        active = _active_version(session, d)
        if active is None:
            continue
        other_docs = [x for x in docs if x.id != d.id]
        for m in _REFERENCE_PATTERN.finditer(active.content_html):
            ref_title = m.group(1).strip()
            if _resolve_reference(session, ref_title, other_docs) is None:
                broken_refs.append({"document_id": d.id, "document_title": d.title, "ref_title": ref_title})

    # duplicate titles within the same doc_type
    by_type_title: dict[tuple, list[str]] = defaultdict(list)
    for d in docs:
        by_type_title[(d.doc_type, d.title.strip().lower())].append(d.title)
    duplicate_titles = [{"doc_type": k[0], "title": v[0], "count": len(v)} for k, v in by_type_title.items() if len(v) > 1]

    # illustration coverage
    uncovered = []
    for c in characters:
        if c.id not in illustrated_entity_ids:
            uncovered.append({"entity_type": "character", "name": c.name})
    for n in npcs:
        if n.id not in illustrated_entity_ids:
            uncovered.append({"entity_type": "npc", "name": n.name})
    for loc in locations:
        if loc.id not in illustrated_entity_ids:
            uncovered.append({"entity_type": "location", "name": loc.name})

    has_bible = any(d.doc_type == models.DocumentType.CAMPAIGN_BIBLE for d in docs)
    has_session_log = any(d.doc_type == models.DocumentType.SESSION_LOG for d in docs)

    checklist = [
        {"ok": has_bible, "label": "Campaign Bible", "detail": "" if has_bible else "No Campaign Bible document yet."},
        {"ok": len(characters) > 0, "label": "At least one character", "detail": "" if characters else "No player characters created yet."},
        {"ok": len(npcs) > 0, "label": "At least one NPC", "detail": "" if npcs else "No NPCs created yet."},
        {"ok": len(locations) > 0, "label": "At least one location", "detail": "" if locations else "No locations created yet."},
        {"ok": has_session_log, "label": "At least one session log", "detail": "" if has_session_log else "No session logs recorded yet."},
        {"ok": not missing_active, "label": "All documents have content",
         "detail": "" if not missing_active else f"{len(missing_active)} document(s) missing active content: {', '.join(missing_active)}"},
        {"ok": stale_count == 0, "label": "All links in sync", "detail": "" if stale_count == 0 else f"{stale_count} stale link(s)."},
        {"ok": len(broken_refs) == 0, "label": "No broken [[references]]",
         "detail": "" if not broken_refs else f"{len(broken_refs)} broken reference(s): " + _describe_broken_refs(broken_refs)},
        {"ok": len(duplicate_titles) == 0, "label": "No duplicate document titles",
         "detail": "" if not duplicate_titles else ", ".join(f'{d["title"]!r} ({d["count"]}x)' for d in duplicate_titles)},
    ]
    for u in uncovered:
        checklist.append({"ok": False, "label": f"Illustration: {u['name']}", "detail": f"No illustration attached to {u['name']}."})
    if not uncovered and (characters or npcs or locations):
        checklist.append({"ok": True, "label": "All characters/NPCs/locations illustrated", "detail": ""})

    return {
        "campaign_id": campaign_id,
        "document_count": len(docs),
        "documents_missing_active_version": missing_active,
        "total_links": len(links),
        "stale_links": stale_count,
        "synced_links": len(links) - stale_count,
        "coherent": stale_count == 0 and not missing_active,
        "links": link_reports,
        "broken_references": broken_refs,
        "duplicate_titles": duplicate_titles,
        "uncovered_illustrations": uncovered,
        "checklist": checklist,
        "ready": all(item["ok"] for item in checklist),
    }
