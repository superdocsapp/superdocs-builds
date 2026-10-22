from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any


BLOCKED_TAGS = {"script", "form", "iframe", "object", "embed", "meta", "base", "link"}
VOID_TAGS = {"area", "base", "br", "col", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node | str"] = field(default_factory=list)

    def text(self) -> str:
        return " ".join(
            "".join(child if isinstance(child, str) else child.text() for child in self.children).split()
        )


class TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag.lower(), {name.lower(): value or "" for name, value in attrs})
        self.stack[-1].children.append(node)
        if tag.lower() not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag.lower(), {name.lower(): value or "" for name, value in attrs})
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag.lower():
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


@dataclass
class ChunkInfo:
    chunk_id: str
    heading_path: str | None
    heading_level: int | None
    signature: str


@dataclass
class DocumentStructure:
    root: Node
    chunks: list[ChunkInfo]
    chunk_paths: dict[str, str]
    path_chunks: dict[str, list[str]]
    nodes_by_chunk: dict[str, Node]


def _first_heading(node: Node) -> tuple[int, str] | None:
    match = re.fullmatch(r"h([1-6])", node.tag)
    if match and node.text():
        return int(match.group(1)), node.text()
    for child in node.children:
        if isinstance(child, Node):
            found = _first_heading(child)
            if found:
                return found
    return None


def _signature(node: Node) -> str:
    """Compare one chunk without treating nested chunk changes as parent changes."""
    parts = [node.tag]
    parts.extend(f"{key}={value}" for key, value in sorted(node.attrs.items()))

    def add(child: Node | str) -> None:
        if isinstance(child, str):
            parts.append(" ".join(child.split()))
            return
        nested_id = child.attrs.get("data-chunk-id")
        if nested_id:
            parts.append(f"CHUNK:{nested_id}")
            return
        parts.append(child.tag)
        for nested in child.children:
            add(nested)

    for child in node.children:
        add(child)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def parse_document_html(document_html: str | None) -> DocumentStructure:
    parser = TreeParser()
    parser.feed(document_html or "")
    headings: dict[int, str] = {}
    chunks: list[ChunkInfo] = []
    nodes_by_chunk: dict[str, Node] = {}

    def walk(node: Node) -> None:
        heading = _first_heading(node) if node.attrs.get("data-chunk-id") else None
        own_heading = re.fullmatch(r"h([1-6])", node.tag)
        if own_heading and node.text():
            heading = (int(own_heading.group(1)), node.text())
        if heading:
            level, title = heading
            headings[level] = title
            for stale in [key for key in headings if key > level]:
                headings.pop(stale)
        chunk_id = node.attrs.get("data-chunk-id")
        if chunk_id and chunk_id not in nodes_by_chunk:
            path = " > ".join(headings[level] for level in sorted(headings)) or None
            chunks.append(ChunkInfo(chunk_id, path, heading[0] if heading else None, _signature(node)))
            nodes_by_chunk[chunk_id] = node
        for child in node.children:
            if isinstance(child, Node):
                walk(child)

    for child in parser.root.children:
        if isinstance(child, Node):
            walk(child)

    chunk_paths = {chunk.chunk_id: chunk.heading_path for chunk in chunks if chunk.heading_path}
    path_chunks: dict[str, list[str]] = {}
    for index, chunk in enumerate(chunks):
        if chunk.heading_level is None or not chunk.heading_path:
            continue
        section = [chunk.chunk_id]
        for following in chunks[index + 1 :]:
            if following.heading_level is not None and following.heading_level <= chunk.heading_level:
                break
            section.append(following.chunk_id)
        path_chunks[chunk.heading_path] = list(dict.fromkeys(section))
    return DocumentStructure(parser.root, chunks, chunk_paths, path_chunks, nodes_by_chunk)


def resolve_changes(changes: list[dict[str, Any]], structure: DocumentStructure) -> list[dict[str, Any]]:
    resolved = []
    for original in changes:
        change = dict(original)
        placement_id = (
            change.get("insert_after_chunk_id")
            if change.get("operation") == "create"
            else change.get("chunk_id")
        )
        change["resolved_section_path"] = structure.chunk_paths.get(placement_id) if placement_id else None
        if change.get("operation") == "create" and not placement_id:
            change["proposal_placement_unavailable"] = True
        resolved.append(change)
    return resolved


def diff_documents(before_html: str, after_html: str, approved_changes: list[dict[str, Any]]) -> dict[str, Any]:
    before = parse_document_html(before_html)
    after = parse_document_html(after_html)
    before_chunks = {chunk.chunk_id: chunk for chunk in before.chunks}
    after_chunks = {chunk.chunk_id: chunk for chunk in after.chunks}
    modified = sorted(
        chunk_id
        for chunk_id in before_chunks.keys() & after_chunks.keys()
        if before_chunks[chunk_id].signature != after_chunks[chunk_id].signature
    )
    new = sorted(after_chunks.keys() - before_chunks.keys())
    deleted = sorted(before_chunks.keys() - after_chunks.keys())
    approved_existing = {
        change.get("chunk_id")
        for change in approved_changes
        if change.get("operation") in {"edit", "delete"} and change.get("chunk_id")
    }
    unrelated = sorted((set(modified) | set(deleted)) - approved_existing)
    applied_ids = list(dict.fromkeys(modified + new + deleted))
    paths = []
    for chunk_id in modified + new:
        if after.chunk_paths.get(chunk_id):
            paths.append(after.chunk_paths[chunk_id])
    for chunk_id in deleted:
        if before.chunk_paths.get(chunk_id):
            paths.append(before.chunk_paths[chunk_id])
    unique_paths = list(dict.fromkeys(paths))
    post_order=[chunk.chunk_id for chunk in after.chunks]
    create_placements=[]
    for change in approved_changes:
        if change.get("operation")!="create": continue
        anchor=change.get("insert_after_chunk_id"); placed=[]; verified=None
        if anchor and anchor in post_order:
            index=post_order.index(anchor)+1
            while index<len(post_order) and post_order[index] in new:
                placed.append(post_order[index]); index+=1
            verified=bool(placed)
        create_placements.append({"change_id":change.get("change_id"),"insert_after_chunk_id":anchor,"new_chunk_ids_after_anchor":placed,"placement_verified":verified})
    return {
        "changed_chunk_ids": modified,
        "new_chunk_ids": new,
        "deleted_chunk_ids": deleted,
        "unrelated_chunk_ids": unrelated,
        "unrelated_changes_detected": bool(unrelated),
        "applied_chunk_ids": applied_ids,
        "applied_target_path": unique_paths[0] if len(unique_paths) == 1 else None,
        "applied_target_paths": unique_paths,
        "create_placements": create_placements,
    }


def _render(node: Node, markers: dict[str, set[str]], labelled: set[str]) -> str:
    if node.tag in BLOCKED_TAGS:
        return ""
    attrs = {
        key: value
        for key, value in node.attrs.items()
        if not key.startswith("on") and key not in {"srcdoc", "action", "formaction"}
    }
    chunk_id = attrs.get("data-chunk-id")
    chunk_markers = markers.get(chunk_id or "", set())
    if chunk_markers:
        existing = attrs.get("class", "")
        attrs["class"] = " ".join(filter(None, [existing, *[f"benchmark-{name}" for name in sorted(chunk_markers)]]))
        labels = [
            label
            for name, label in (("expected", "Expected section"), ("proposed", "SuperDocs proposal"), ("applied", "Applied change"))
            if name in chunk_markers and name not in labelled
        ]
        if labels:
            attrs["data-benchmark-markers"] = " · ".join(labels)
            labelled.update(chunk_markers)
    attr_text = "".join(f' {html.escape(key)}="{html.escape(value, quote=True)}"' for key, value in attrs.items())
    children = "".join(html.escape(child) if isinstance(child, str) else _render(child, markers, labelled) for child in node.children)
    if node.tag in VOID_TAGS:
        return f"<{node.tag}{attr_text}>"
    return f"<{node.tag}{attr_text}>{children}</{node.tag}>"


def render_annotated_document(
    document_html: str,
    expected_path: str | None,
    proposed_chunk_ids: list[str],
    applied_chunk_ids: list[str],
    expected_chunk_ids: list[str] | None = None,
) -> str:
    structure = parse_document_html(document_html)
    markers: dict[str, set[str]] = {}
    for chunk_id in expected_chunk_ids if expected_chunk_ids is not None else structure.path_chunks.get(expected_path or "", []):
        markers.setdefault(chunk_id, set()).add("expected")
    for chunk_id in proposed_chunk_ids:
        if chunk_id in structure.nodes_by_chunk:
            markers.setdefault(chunk_id, set()).add("proposed")
    for chunk_id in applied_chunk_ids:
        if chunk_id in structure.nodes_by_chunk:
            markers.setdefault(chunk_id, set()).add("applied")
    labelled: set[str] = set()
    body = "".join(
        html.escape(child) if isinstance(child, str) else _render(child, markers, labelled)
        for child in structure.root.children
    )
    style = """
    html,body{margin:0;padding:0;background:#fff;color:#172033;font:15px/1.55 system-ui,sans-serif}
    body{padding:24px} table{border-collapse:collapse;max-width:100%} td,th{border:1px solid #ccd3df;padding:6px}
    [data-benchmark-markers]::before{content:attr(data-benchmark-markers);display:block;width:max-content;max-width:100%;font:700 11px/1.3 system-ui;padding:3px 7px;margin:2px 0 5px;background:#fff;color:#111;border:1px solid currentColor;border-radius:4px}
    .benchmark-expected{outline:3px solid #1769aa;outline-offset:2px}
    .benchmark-proposed{box-shadow:0 0 0 3px #9a5b00;outline:2px dashed #9a5b00;outline-offset:5px}
    .benchmark-applied{border-left:6px double #157347!important;padding-left:8px!important}
    """
    return f"<!doctype html><html><head><meta charset='utf-8'><meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:\"><style>{style}</style></head><body>{body}</body></html>"
