"""Typed, heading-based staging document contract for M1.2."""
from __future__ import annotations
import html
import hashlib
import re
from html.parser import HTMLParser
from dataclasses import dataclass, asdict
from typing import Any
from .m1 import QUOTES

REQUIRED = ("SAFETY_GATE","PROCEDURE_1","PROCEDURE_2","PROCEDURE_3","SPECIFICATION","RESTART_CHECK")
ALL_SLOTS = ("TASK_OVERVIEW","SAFETY_GATE","PROCEDURE_1","PROCEDURE_2","PROCEDURE_3","SPECIFICATION","RESTART_CHECK","STOP_ESCALATE")
HEADINGS = {"TASK_OVERVIEW":"Task Overview","SAFETY_GATE":"Safety Gate","PROCEDURE_1":"Procedure Step 1","PROCEDURE_2":"Procedure Step 2","PROCEDURE_3":"Procedure Step 3","SPECIFICATION":"Specification","RESTART_CHECK":"Restart Check","STOP_ESCALATE":"Stop / Escalate"}


def normalize_document_identities(roster: list[dict[str, Any]], *, staging_hint: str | None = None,
                                  manual_hint: str | None = None) -> dict[str, set[str]]:
    """Return equivalence classes for session-local and durable roster IDs."""
    result: dict[str, set[str]] = {}
    for entry in roster:
        values = {str(x) for x in (entry.get("document_id"), entry.get("durable_document_id")) if x}
        if values:
            result[str(entry.get("document_id") or entry.get("durable_document_id"))] = values
    return result


def same_document(value: str | None, forms: set[str]) -> bool:
    return bool(value and value in forms)

@dataclass(frozen=True)
class StagingSection:
    slot_id: str
    heading: str
    base_text: str
    evidence_ids: tuple[str,...] = ()
    editable: bool = False
    required: bool = True
    authoritative_chunk_id: str | None = None
    provider_chunk_ids: tuple[str, ...] = ()


def _plain(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def fingerprint(value: str) -> str:
    """Stable fingerprint for provider-normalized HTML/text comparisons."""
    return hashlib.sha256(_plain(value).encode("utf-8")).hexdigest()

def sections() -> list[StagingSection]:
    return [StagingSection("TASK_OVERVIEW",HEADINGS["TASK_OVERVIEW"],"Clear a jam on the infeed.",(),True,False),StagingSection("SAFETY_GATE",HEADINGS["SAFETY_GATE"],QUOTES["SAFE-001"][0]+" Source: PDF p. 1.",("SAFE-001",)),StagingSection("PROCEDURE_1",HEADINGS["PROCEDURE_1"],QUOTES["STEP-001"][0]+" Source: PDF p. 2.",("STEP-001",)),StagingSection("PROCEDURE_2",HEADINGS["PROCEDURE_2"],QUOTES["STEP-002"][0]+" Source: PDF p. 2.",("STEP-002",)),StagingSection("PROCEDURE_3",HEADINGS["PROCEDURE_3"],QUOTES["STEP-003"][0]+" Source: PDF p. 2.",("STEP-003",)),StagingSection("SPECIFICATION",HEADINGS["SPECIFICATION"],QUOTES["SPEC-001"][0]+" Source: PDF p. 3.",("SPEC-001",)),StagingSection("RESTART_CHECK",HEADINGS["RESTART_CHECK"],QUOTES["RESTART-001"][0]+" Source: PDF p. 4.",("RESTART-001",)),StagingSection("STOP_ESCALATE",HEADINGS["STOP_ESCALATE"],"Stop if the interlock fails.",(),True,False)]

def staging_html(items=None) -> str:
    items=items or sections(); return "<!doctype html><html><body><h1>LineCard Content Review</h1>"+"".join(f'<div data-chunk-id="LC_{s.slot_id}"><h2>{html.escape(s.heading)}</h2><p>{html.escape(s.base_text)}</p></div>' for s in items)+"</body></html>"


class _Node:
    def __init__(self, tag: str, attrs: dict[str, str] | None = None, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, attrs or {}, parent, []
    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)
    def html(self) -> str:
        attrs = "".join(f' {k}="{html.escape(v, quote=True)}"' for k,v in self.attrs.items())
        return f"<{self.tag}{attrs}>" + "".join(c if isinstance(c,str) else c.html() for c in self.children) + f"</{self.tag}>"


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.root = _Node("root"); self.stack = [self.root]
    def handle_starttag(self, tag, attrs):
        node = _Node(tag.lower(), dict(attrs), self.stack[-1]); self.stack[-1].children.append(node)
        if tag.lower() not in {"meta", "link", "img", "br", "hr", "input"}: self.stack.append(node)
    def handle_startendtag(self, tag, attrs): self.handle_starttag(tag, attrs); self.handle_endtag(tag)
    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag.lower(): self.stack = self.stack[:i]; return
    def handle_data(self, data): self.stack[-1].children.append(data)


def parse_document_sync(authoritative_html: str, *, document_id: str, version: Any = None,
                        local=None) -> dict[str, dict[str, Any]]:
    """Build the authoritative slot map from the provider's prepared HTML.

    Chunk identity comes only from document_sync.  Heading and fingerprints are
    integrity checks used after the direct chunk-id lookup, never as fallbacks.
    """
    if not document_id: raise ValueError("document_sync requires an explicit document_id")
    local = local or sections(); by_heading = {s.heading.casefold(): s for s in local}
    parser = _Tree(); parser.feed(authoritative_html)
    found: dict[str, dict[str, Any]] = {}; chunks: dict[str, str] = {}
    nodes: list[_Node] = []
    headings_in_order: list[tuple[_Node, str, str]] = []
    def collect(node):
        if not isinstance(node, _Node): return
        nodes.append(node)
        if node.tag in {"h1", "h2", "h3", "h4"}:
            text = _plain(node.text()); slot = by_heading.get(text.casefold())
            if slot: headings_in_order.append((node, slot.slot_id, text))
        for child in node.children: collect(child)
    collect(parser.root)
    # A provider chunk is owned by the LC heading boundary containing it.  A
    # wrapper spanning several headings is assigned to its first heading;
    # nested/block chunks still resolve to their own heading boundary.
    heading_index = {id(node): i for i, (node, _, _) in enumerate(headings_in_order)}
    def chunk_owner(node: _Node) -> str | None:
        contained = [i for i, (h, _, _) in enumerate(headings_in_order)
                     if any(h is n for n in descendants_nodes(node))]
        if contained: return headings_in_order[min(contained)][1]
        preceding = [i for i, (h, _, _) in enumerate(headings_in_order)
                     if nodes.index(h) < nodes.index(node)]
        return headings_in_order[max(preceding)][1] if preceding else None
    def descendants_nodes(node):
        result = []
        def add(n):
            if not isinstance(n, _Node): return
            result.append(n)
            for child in n.children: add(child)
        add(node); return result
    for node in nodes:
        chunk = node.attrs.get("data-chunk-id")
        if not chunk: continue
        slot_id = chunk_owner(node)
        if slot_id is not None:
            if chunk in chunks and chunks[chunk] != slot_id:
                raise ValueError(f"provider chunk assigned to multiple staging slots: {chunk}")
            chunks[chunk] = slot_id
    def walk(node):
        if not isinstance(node, _Node): return
        headings = []
        def descendants(n):
            if isinstance(n, _Node):
                if n.tag in {"h1", "h2", "h3", "h4"}: headings.append(_plain(n.text()))
                for child in n.children: descendants(child)
        descendants(node)
        if "data-chunk-id" not in node.attrs:
            orphan_headings = [_plain(child.text()) for child in node.children if isinstance(child, _Node) and child.tag in {"h1", "h2", "h3", "h4"}]
            for heading in orphan_headings:
                if heading.casefold() in by_heading and by_heading[heading.casefold()].slot_id in found:
                    raise ValueError(f"duplicate staging heading: {heading}")
        owned_headings = []
        if "data-chunk-id" in node.attrs:
            for candidate in descendants_nodes(node):
                if candidate.tag not in {"h1", "h2", "h3", "h4"}: continue
                owner = candidate
                while owner is not None and "data-chunk-id" not in owner.attrs: owner = owner.parent
                if owner is node: owned_headings.append(_plain(candidate.text()))
        for heading in owned_headings:
            slot = by_heading.get(heading.casefold())
            if slot is None: continue
            owner = node
            while owner is not None and "data-chunk-id" not in owner.attrs: owner = owner.parent
            if owner is None: raise ValueError(f"heading has no provider data-chunk-id: {heading}")
            chunk = owner.attrs["data-chunk-id"]
            if slot.slot_id in found: raise ValueError(f"duplicate staging heading: {heading}")
            owned = sorted((c for c, owner_slot in chunks.items() if owner_slot == slot.slot_id), key=lambda c: nodes.index(next(n for n in nodes if n.attrs.get("data-chunk-id") == c)))
            if chunk not in owned: owned.insert(0, chunk)
            found[slot.slot_id] = {
                "slot_id": slot.slot_id, "heading": heading, "authoritative_chunk_id": chunk,
                "root_chunk_id": chunk, "heading_chunk_id": node.attrs.get("data-chunk-id"),
                "provider_chunk_ids": owned,
                "authoritative_document_id": document_id, "document_id_forms": {document_id}, "old_html": owner.html(),
                "old_html_fingerprint": fingerprint(owner.html()),
                "old_text_fingerprint": fingerprint(owner.text()), "text": _plain(owner.text()),
                "evidence_ids": list(slot.evidence_ids), "critical": slot.required,
                "editable": slot.editable, "base_version": version,
            }; chunks[chunk] = slot.slot_id
        for child in node.children: walk(child)
    walk(parser.root)
    for s in local:
        count = len(re.findall(rf"<h[1-4][^>]*>\s*{re.escape(s.heading)}\s*</h[1-4]>", authoritative_html, re.I))
        if count > 1: raise ValueError(f"duplicate staging heading: {s.heading}")
    missing = [s.slot_id for s in local if s.slot_id not in found]
    if missing: raise ValueError(f"missing staging slots: {','.join(missing)}")
    for slot_id, item in found.items():
        item["provider_chunk_ids"] = sorted({c for c, owner in chunks.items() if owner == slot_id}, key=lambda c: next(i for i,n in enumerate(nodes) if n.attrs.get("data-chunk-id") == c))
        item["root_chunk_id"] = item["root_chunk_id"] if item["root_chunk_id"] in item["provider_chunk_ids"] else None
    return found

def map_authoritative_sections(authoritative_html: str, local=None, *, document_id: str = "offline-staging", version: Any = None) -> dict[str, dict[str, Any]]:
    # Compatibility entry point: authoritative synchronization is the only
    # supported source of provider chunk identity.
    return parse_document_sync(authoritative_html, document_id=document_id, version=version, local=local)
    local=local or sections(); found={}
    for match in re.finditer(r"<h2[^>]*>\s*(.*?)\s*</h2>\s*<p[^>]*>(.*?)</p>",authoritative_html,re.S|re.I):
        heading=re.sub(r"<[^>]+>","",match.group(1)).strip(); body=re.sub(r"<[^>]+>","",match.group(2)).strip()
        slots=[s for s in local if s.heading == heading]
        if len(slots)==1:
            if slots[0].slot_id in found: raise ValueError(f"duplicate staging heading: {heading}")
            slot = slots[0]
            found[slot.slot_id]={
                "slot_id": slot.slot_id,
                "heading": heading,
                "authoritative_chunk_id": f"heading:{heading}",
                "authoritative_document_id": document_id,
                "old_html_fingerprint": fingerprint(match.group(0)),
                "old_text_fingerprint": fingerprint(body),
                "text": body,
                "evidence_ids": list(slot.evidence_ids),
                "critical": slot.required,
                "editable": slot.editable,
                "base_version": version,
            }
    missing=[s.slot_id for s in local if s.required and s.slot_id not in found]
    if missing: raise ValueError(f"missing required staging slots: {','.join(missing)}")
    return found

def proposal_slot(proposal: dict[str, Any], mapping: dict[str, dict[str, Any]]) -> str:
    """Resolve a proposal only when every available identity signal agrees.

    Provider proposals are untrusted.  A heading match by itself is not enough;
    the target document, chunk, old fingerprint, section context, and base
    revision are checked whenever the provider supplies them.
    """
    candidates = set(mapping)
    target = proposal.get("document_id") or proposal.get("target_document_id")
    if target:
        candidates &= {s for s, v in mapping.items() if not v.get("authoritative_document_id") or target in set(v.get("document_id_forms", {v.get("authoritative_document_id")}))}
    chunk = proposal.get("chunk_id") or proposal.get("target_chunk_id")
    if not chunk: raise ValueError("proposal has no authoritative chunk_id")
    candidates &= {s for s, v in mapping.items() if chunk in set(v.get("provider_chunk_ids", (v.get("authoritative_chunk_id"),)))}
    old = proposal.get("old_html") or proposal.get("before") or ""
    old_fp = proposal.get("old_html_fingerprint") or proposal.get("old_fingerprint")
    if old_fp:
        candidates &= {s for s, v in mapping.items() if old_fp in {v.get("old_html_fingerprint"), v.get("old_text_fingerprint")}}
    elif old:
        candidates &= {s for s, v in mapping.items() if fingerprint(old) in {v.get("old_html_fingerprint"), v.get("old_text_fingerprint")} or _plain(old) in v.get("text", "")}
    heading = proposal.get("heading") or proposal.get("section") or proposal.get("section_heading")
    if heading:
        candidates &= {s for s, v in mapping.items() if _plain(str(heading)).casefold() == _plain(v["heading"]).casefold() or _plain(str(heading)).casefold() in _plain(v.get("text", "")).casefold()}
    base = proposal.get("base_version") or proposal.get("version") or proposal.get("expected_version")
    if base is not None:
        candidates &= {s for s, v in mapping.items() if v.get("base_version") is None or str(v.get("base_version")) == str(base)}
    if target and not any(same_document(target, set(v.get("document_id_forms", {v.get("authoritative_document_id")}))) for v in mapping.values()):
        raise ValueError("wrong target document")
    if len(candidates) != 1:
        raise ValueError("unknown or ambiguous staging slot")
    return next(iter(candidates))

def critical_change_allowed(slot_id: str, before: str, after: str) -> tuple[bool,str]:
    if slot_id in REQUIRED:
        required=[eid for eid,(_,_,_) in QUOTES.items() if eid.startswith({"SAFETY_GATE":"SAFE","PROCEDURE_1":"STEP","PROCEDURE_2":"STEP","PROCEDURE_3":"STEP","SPECIFICATION":"SPEC","RESTART_CHECK":"RESTART"}.get(slot_id,"__"))]
        if any(QUOTES[eid][0] not in after for eid in required): return False,"critical evidence-backed wording changed or removed"
        if slot_id=="SPECIFICATION" and QUOTES["SPEC-001"][0] not in after: return False,"exact specification changed"
        if "PDF p. " not in after: return False,"visible citation removed"
    return True,"eligible"
