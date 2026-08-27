from __future__ import annotations

from typing import Any


def _as_list(payload: Any) -> list[dict]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("documents", "open_documents", "items", "data"):
            if isinstance(payload.get(key), list):
                return [x for x in payload[key] if isinstance(x, dict)]
        if payload.get("document_id") or payload.get("id"):
            return [payload]
    return []


def document_id_of(doc: dict) -> str | None:
    for k in ("document_id", "id", "doc_id"):
        v = doc.get(k)
        if v:
            return str(v)
    return None


def title_of(doc: dict) -> str:
    return str(doc.get("title") or doc.get("filename") or doc.get("name") or "")


def html_of(doc: dict) -> str | None:
    for k in ("html", "html_content", "document_html"):
        v = doc.get(k)
        if isinstance(v, str) and v:
            return v
    ds = doc.get("document_state") or {}
    if isinstance(ds, dict):
        v = ds.get("html_content") or ds.get("html")
        if isinstance(v, str) and v:
            return v
    return None


def focused_id(payload: Any, index_hint: str | None = None) -> str | None:
    if isinstance(payload, dict):
        for k in ("focused_document_id", "focus_document_id", "document_id"):
            if payload.get(k):
                return str(payload[k])
    docs = _as_list(payload)
    for d in docs:
        if d.get("focused") or d.get("is_focused"):
            did = document_id_of(d)
            if did:
                return did
    if index_hint:
        return index_hint
    if docs:
        return document_id_of(docs[0])
    return None


def find_index_html(payload: Any, index_document_id: str | None) -> str | None:
    docs = _as_list(payload)
    if index_document_id:
        for d in docs:
            if document_id_of(d) == index_document_id:
                h = html_of(d)
                if h:
                    return h
    if isinstance(payload, dict):
        h = html_of(payload)
        if h:
            return h
    for d in docs:
        if d.get("focused") or d.get("is_focused"):
            h = html_of(d)
            if h:
                return h
    return None


def roster_docs(payload: Any) -> list[dict]:
    return _as_list(payload)


def listed_template_name(list_payload: Any, template_id: str | None) -> str | None:
    items = _as_list(list_payload)
    if isinstance(list_payload, dict) and not items:
        inner = list_payload.get("templates")
        if isinstance(inner, list):
            items = [x for x in inner if isinstance(x, dict)]
    for item in items:
        tid = str(item.get("id") or item.get("template_id") or "")
        if template_id and tid == template_id:
            return str(item.get("name") or item.get("filename") or "") or None
    if items:
        return str(items[0].get("name") or items[0].get("filename") or "") or None
    return None
