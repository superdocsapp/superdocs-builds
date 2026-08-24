import hashlib
import json
from typing import Any

CANONICALIZER_VERSION = "docrelay.google-native-canonical.v1"


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _clean_native(value: Any) -> Any:
    """Remove suggestion overlays while retaining native semantic identifiers."""
    if isinstance(value, list):
        return [_clean_native(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        str(key): _clean_native(item)
        for key, item in value.items()
        if not str(key).lower().startswith("suggested")
        and str(key).lower() not in {"suggestionsviewmode", "commentsviewmode"}
    }


def _paragraph_runs(paragraph: dict[str, Any]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for element in paragraph.get("elements") or []:
        start_index = element.get("startIndex")
        end_index = element.get("endIndex")
        if "textRun" in element:
            text_run = element.get("textRun") or {}
            text = str(text_run.get("content") or "")
            style = _clean_native(text_run.get("textStyle") or {})
            if runs and runs[-1].get("kind") == "text" and runs[-1].get("style") == style:
                runs[-1]["text"] += text
                runs[-1]["endIndex"] = end_index
            else:
                runs.append(
                    {
                        "kind": "text",
                        "startIndex": start_index,
                        "endIndex": end_index,
                        "text": text,
                        "style": style,
                    }
                )
            continue
        kind = next(
            (
                name
                for name in (
                    "autoText",
                    "pageBreak",
                    "columnBreak",
                    "footnoteReference",
                    "horizontalRule",
                    "equation",
                    "inlineObjectElement",
                    "person",
                    "richLink",
                    "dateElement",
                )
                if name in element
            ),
            "unknown",
        )
        runs.append(
            {
                "kind": kind,
                "startIndex": start_index,
                "endIndex": end_index,
                "value": _clean_native(element.get(kind) or element),
            }
        )
    return runs


def _canonical_paragraph(paragraph: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "paragraph",
        "paragraphStyle": _clean_native(paragraph.get("paragraphStyle") or {}),
        "bullet": _clean_native(paragraph.get("bullet")) if paragraph.get("bullet") else None,
        "positionedObjectIds": sorted(paragraph.get("positionedObjectIds") or []),
        "runs": _paragraph_runs(paragraph),
    }


def _canonical_structural(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for element in elements:
        common = {
            "startIndex": element.get("startIndex"),
            "endIndex": element.get("endIndex"),
        }
        if "paragraph" in element:
            result.append({**common, **_canonical_paragraph(element.get("paragraph") or {})})
        elif "sectionBreak" in element:
            result.append(
                {
                    **common,
                    "type": "sectionBreak",
                    "sectionStyle": _clean_native(
                        (element.get("sectionBreak") or {}).get("sectionStyle") or {}
                    ),
                }
            )
        elif "table" in element:
            table = element.get("table") or {}
            rows = []
            for row in table.get("tableRows") or []:
                cells = [
                    {
                        "content": _canonical_structural(cell.get("content") or []),
                        "tableCellStyle": _clean_native(cell.get("tableCellStyle") or {}),
                    }
                    for cell in row.get("tableCells") or []
                ]
                rows.append(
                    {
                        "cells": cells,
                        "tableRowStyle": _clean_native(row.get("tableRowStyle") or {}),
                    }
                )
            result.append(
                {
                    **common,
                    "type": "table",
                    "rows": table.get("rows"),
                    "columns": table.get("columns"),
                    "tableRows": rows,
                    "tableStyle": _clean_native(table.get("tableStyle") or {}),
                }
            )
        elif "tableOfContents" in element:
            result.append(
                {
                    **common,
                    "type": "tableOfContents",
                    "content": _canonical_structural(
                        (element.get("tableOfContents") or {}).get("content") or []
                    ),
                }
            )
        else:
            result.append({**common, "type": "unknown", "value": _clean_native(element)})
    return result


def _canonical_segments(segments: dict[str, Any]) -> dict[str, Any]:
    return {
        str(segment_id): {"content": _canonical_structural((segment or {}).get("content") or [])}
        for segment_id, segment in segments.items()
    }


def _canonical_tab(tab: dict[str, Any]) -> dict[str, Any]:
    properties = tab.get("tabProperties") or {}
    document_tab = tab.get("documentTab") or {}
    return {
        "tabProperties": {
            "tabId": properties.get("tabId"),
            "title": properties.get("title"),
            "index": properties.get("index"),
            "nestingLevel": properties.get("nestingLevel"),
            "parentTabId": properties.get("parentTabId"),
        },
        "body": _canonical_structural((document_tab.get("body") or {}).get("content") or []),
        "headers": _canonical_segments(document_tab.get("headers") or {}),
        "footers": _canonical_segments(document_tab.get("footers") or {}),
        "footnotes": _canonical_segments(document_tab.get("footnotes") or {}),
        "documentStyle": _clean_native(document_tab.get("documentStyle") or {}),
        "namedStyles": _clean_native(document_tab.get("namedStyles") or {}),
        "lists": _clean_native(document_tab.get("lists") or {}),
        "namedRanges": _clean_native(document_tab.get("namedRanges") or {}),
        "inlineObjects": _clean_native(document_tab.get("inlineObjects") or {}),
        "positionedObjects": _clean_native(document_tab.get("positionedObjects") or {}),
        "childTabs": [_canonical_tab(child) for child in tab.get("childTabs") or []],
    }


def canonicalize_google_document(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": CANONICALIZER_VERSION,
        "tabs": [_canonical_tab(tab) for tab in document.get("tabs") or []],
    }
