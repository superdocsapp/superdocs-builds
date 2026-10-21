"""Select the local domain artifact for SuperDocs HTML export.

Export does not target SuperDocs session documents by id. Current docs for
POST /v1/documents/export accept html, session_id, or upload_id. Sending only
session_id exports the session default document. This module chooses the
local FrameworkDocument or RoleProfile by semantic kind and renders HTML.
"""

from __future__ import annotations

from typing import Any

from job_architecture.documents import render_framework_html, render_profile_html
from job_architecture.framework import FrameworkDocument
from job_architecture.live.state import LiveState
from job_architecture.live.subset import DemoSubset
from job_architecture.models import RoleProfile
from job_architecture.superdocs.errors import SuperDocsError
from job_architecture.superdocs.models import ExportRequest

EXPORTABLE_KINDS = frozenset({"framework", "profile"})


def documents_with_kind(state: LiveState, kind: str) -> list[dict[str, Any]]:
    """Return records whose semantic `kind` field equals `kind`. Order is not used."""
    return [item for item in state.documents if item.get("kind") == kind]


def require_export_kind(kind: str) -> str:
    if kind not in EXPORTABLE_KINDS:
        raise SuperDocsError(
            f"Export kind must be one of {sorted(EXPORTABLE_KINDS)}; got {kind!r}"
        )
    return kind


def get_framework_for_export(framework: FrameworkDocument) -> FrameworkDocument:
    """The live workflow has exactly one approved FrameworkDocument."""
    if framework is None:
        raise SuperDocsError("No FrameworkDocument to export")
    return framework


def get_profile_for_export(framework: FrameworkDocument, subset: DemoSubset) -> RoleProfile:
    """Return exactly one RoleProfile for live profile export."""
    if subset.surgical_role_id:
        matches = [item for item in framework.profiles if item.role_id == subset.surgical_role_id]
        if not matches:
            raise SuperDocsError(
                f"No profile matches surgical_role_id={subset.surgical_role_id!r}"
            )
        if len(matches) > 1:
            raise SuperDocsError(
                f"Ambiguous profile: {len(matches)} records match "
                f"surgical_role_id={subset.surgical_role_id!r}; refusing to guess"
            )
        return matches[0]
    subset_ids = set(subset.role_ids)
    matches = [item for item in framework.profiles if item.role_id in subset_ids]
    classified = [item for item in matches if item.classification == "strong_fit"]
    candidates = classified or matches
    if not candidates:
        raise SuperDocsError("No RoleProfile to export")
    if len(candidates) > 1:
        raise SuperDocsError(
            f"Ambiguous profile: {len(candidates)} subset profiles; refusing to guess"
        )
    return candidates[0]


def build_export_request(
    kind: str,
    *,
    session_id: str,
    filename: str,
    framework: FrameworkDocument,
    subset: DemoSubset,
) -> ExportRequest:
    kind = require_export_kind(kind)
    if kind == "framework":
        html = render_framework_html(get_framework_for_export(framework))
    else:
        html = render_profile_html(get_profile_for_export(framework, subset))
    return ExportRequest(
        session_id=session_id,
        html=html,
        format="docx",
        filename=filename,
    )
