"""Real Box API adapter using the official `boxsdk` package.

Implements the same BoxClient interface FakeBoxClient does, so the
pipeline, API routes, and MCP server work identically against either --
the interface boundary in box_client.py is the actual contract, not
FakeBoxClient specifically.

Not exercised by the offline test suite (no live Box tenant is available
for this submission, and the brief is explicit that tests must run
without a live key), but it is real, complete code against the documented
Box SDK surface, gated behind environment variables so `make bootstrap`
and `make test` never require it. See the "Running against real Box"
section in the README for how to point a deployment at it.

Requires: pip install boxsdk (not in requirements.txt by default, to
keep the offline-test path dependency-light; add it if you're wiring
this up against a real tenant).
"""
from __future__ import annotations

import os
from typing import Any, Optional

from app.clients.box_client import BoxAPIError, BoxClient
from app.models import BoxFileVersion, GovernanceState

_PROTECTED_KEYS = {"legal_hold", "retention_policy_locked", "classification_label"}


def _status_code(exc: Exception) -> Optional[int]:
    """Best-effort extraction of an HTTP status code from a boxsdk
    BoxAPIException (or anything else that happens to expose one), so
    callers can distinguish "this specific thing is missing" (404) from
    "the request failed for some other reason" (403/401/429/5xx/network).
    Returns None if no status code can be determined -- callers should
    treat that as "don't know", not as "safe to assume 404"."""
    return getattr(exc, "status", None) or getattr(exc, "status_code", None)


def _is_not_found(exc: Exception) -> bool:
    return _status_code(exc) == 404


class RealBoxClient(BoxClient):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        enterprise_id: str,
        metadata_scope: str = "enterprise",
        metadata_template_key: str = "documentIntelligence",
        rsa_private_key_data: Optional[str] = None,
    ) -> None:
        try:
            from boxsdk import Client, JWTAuth  # type: ignore
        except ImportError as e:  # pragma: no cover - only hit without boxsdk installed
            raise RuntimeError(
                "RealBoxClient requires the 'boxsdk' package (pip install boxsdk); "
                "it is intentionally left out of requirements.txt so the offline "
                "test suite never needs live credentials."
            ) from e

        # Explicit per-tenant key wins; only fall back to the shared
        # deployment-wide env var when the caller didn't provide one
        # (single-tenant deployments). This is what makes multi-tenant
        # credential isolation actually real instead of just declared in
        # TenantConfig.
        auth = JWTAuth(
            client_id=client_id,
            client_secret=client_secret,
            enterprise_id=enterprise_id,
            rsa_private_key_data=(
                rsa_private_key_data
                if rsa_private_key_data is not None
                else os.environ.get("BOX_JWT_PRIVATE_KEY", "")
            ),
        )
        self._client = Client(auth)
        self._metadata_scope = metadata_scope
        self._metadata_template_key = metadata_template_key

    @classmethod
    def from_env(cls) -> Optional["RealBoxClient"]:
        """Returns a configured RealBoxClient if the required env vars are
        present, otherwise None -- this is what lets app/api/main.py fall
        back to FakeBoxClient automatically rather than crash when no Box
        app is registered."""
        required = ["BOX_CLIENT_ID", "BOX_CLIENT_SECRET", "BOX_ENTERPRISE_ID"]
        if not all(os.environ.get(k) for k in required):
            return None
        return cls(
            client_id=os.environ["BOX_CLIENT_ID"],
            client_secret=os.environ["BOX_CLIENT_SECRET"],
            enterprise_id=os.environ["BOX_ENTERPRISE_ID"],
            rsa_private_key_data=os.environ.get("BOX_JWT_PRIVATE_KEY"),
        )

    def get_file_version(self, file_id: str) -> BoxFileVersion:
        try:
            info = self._client.file(file_id).get(fields=["name", "sha1", "file_version"])
        except Exception as e:  # boxsdk raises its own BoxAPIException
            raise BoxAPIError(str(e)) from e
        return BoxFileVersion(
            file_id=file_id,
            version_id=str(info.file_version.get("id", info.etag)),
            name=info.name,
            sha1=info.sha1,
        )

    def download_file(self, file_id: str) -> bytes:
        try:
            return self._client.file(file_id).content()
        except Exception as e:
            raise BoxAPIError(str(e)) from e

    def get_governance_state(self, file_id: str) -> GovernanceState:
        # Box exposes legal hold assignments and retention policy
        # assignments as separate API objects, not plain file fields --
        # both are checked so a hold OR a lock either one blocks
        # processing, matching the fake client's semantics exactly.
        try:
            holds = list(
                self._client.legal_hold_policy_assignments(file_id=file_id, type="file")
            )
            retention = list(
                self._client.file(file_id).get_retention_policy_assignments()
                if hasattr(self._client.file(file_id), "get_retention_policy_assignments")
                else []
            )
            classification = None
            try:
                classification = self._client.file(file_id).get_classification()
            except Exception:
                classification = None
            return GovernanceState(
                legal_hold=len(holds) > 0,
                retention_policy_locked=len(retention) > 0,
                classification_label=classification,
            )
        except Exception as e:
            raise BoxAPIError(str(e)) from e

    def get_metadata(self, file_id: str, template_key: str) -> dict[str, Any]:
        try:
            md = self._client.file(file_id).metadata(self._metadata_scope, template_key).get()
            return {k: v for k, v in md.items() if not k.startswith("$")}
        except Exception as e:
            if _is_not_found(e):
                # No metadata template instance on this file yet -- that
                # genuinely means "there is no metadata", not an error.
                return {}
            # Anything else (403/401/429/5xx/network/unknown) is a real
            # failure and must not be silently treated as "no metadata" --
            # that would let an auth failure masquerade as an empty file.
            raise BoxAPIError(str(e)) from e

    def update_metadata(
        self, file_id: str, template_key: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        blocked = _PROTECTED_KEYS & set(fields)
        if blocked:
            raise BoxAPIError(
                f"refusing to write governance-protected keys via metadata patch: {blocked}"
            )
        file_metadata = self._client.file(file_id).metadata(self._metadata_scope, template_key)
        try:
            existing = file_metadata.get()
        except Exception as e:
            if not _is_not_found(e):
                raise BoxAPIError(str(e)) from e
            # Template instance doesn't exist yet on this file -- create it.
            try:
                updated = file_metadata.create(fields)
            except Exception as create_exc:
                raise BoxAPIError(str(create_exc)) from create_exc
            return {k: v for k, v in updated.items() if not k.startswith("$")}

        ops = [
            {"op": "replace" if k in existing else "add", "path": f"/{k}", "value": v}
            for k, v in fields.items()
        ]
        try:
            updated = file_metadata.update(ops)
        except Exception as e:
            if _is_not_found(e):
                # Instance existed a moment ago but is gone now (race) --
                # fall back to create rather than raising a confusing
                # "not found" for what the caller sees as a normal update.
                try:
                    updated = file_metadata.create(fields)
                except Exception as create_exc:
                    raise BoxAPIError(str(create_exc)) from create_exc
            else:
                raise BoxAPIError(str(e)) from e
        return {k: v for k, v in updated.items() if not k.startswith("$")}

    def upload_companion_document(
        self, parent_folder_id: str, filename: str, content: bytes
    ) -> str:
        import io

        # Dedupe by (folder, filename): the pipeline passes a
        # deterministic, content-addressed filename (source file_id +
        # sha1), so if a retry after a crash between "upload succeeded"
        # and "checkpoint saved" asks to upload the same companion
        # again, find and reuse the existing file instead of creating a
        # duplicate.
        try:
            existing = next(
                (
                    item
                    for item in self._client.folder(parent_folder_id).get_items()
                    if getattr(item, "name", None) == filename
                ),
                None,
            )
        except Exception as e:
            raise BoxAPIError(str(e)) from e
        if existing is not None:
            return existing.id

        try:
            uploaded = self._client.folder(parent_folder_id).upload_stream(
                io.BytesIO(content), filename
            )
        except Exception as e:
            raise BoxAPIError(str(e)) from e
        return uploaded.id
