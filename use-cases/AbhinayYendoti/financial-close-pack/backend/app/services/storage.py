"""Content-addressed storage, on S3-compatible object storage or local disk.

Uploads, generated artifacts and exported packs all land here. The key space is the
same on both backends (`closes/{close_id}/documents/{id}`), so nothing above this
module knows or cares which one is live.

`S3_ENDPOINT_URL` + `S3_ACCESS_KEY_ID` + `S3_BUCKET_NAME` select object storage; the
endpoint is not hardcoded to any vendor, so Storj, Cloudflare R2 and AWS S3 all work
through the same client. Left blank, everything falls back to `STORAGE_DIR` on local
disk, which is what the test suite runs on.

Both backends return the same receipt - `{key, size, sha256}` - and the digest is
computed here from the bytes we actually wrote, never taken from a provider ETag,
which for multipart uploads is not a content hash at all.
"""

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Any, BinaryIO

_CHUNK = 1024 * 256


def _use_s3() -> bool:
    from ..core.config import settings

    return settings.s3_enabled


_client: Any = None


def _s3() -> Any:
    """One cached boto3 client. Creating one per call re-resolves the endpoint each time."""
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

        from ..core.config import settings

        # boto3 >= 1.36 defaults to sending payloads with aws-chunked transfer encoding
        # and a trailing CRC32 checksum. AWS accepts it; S3-compatible gateways largely
        # do not - Storj rejects those requests with `MissingContentLength`. Asking for
        # checksums only "when_required" restores a plain Content-Length upload.
        _client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region or None,
            config=Config(
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                signature_version="s3v4",
            ),
        )
    return _client


def reset_client_for_tests() -> None:
    global _client
    _client = None


def _bucket() -> str:
    from ..core.config import settings

    return settings.s3_bucket_name


def _root() -> Path:
    from ..core.config import settings

    root = Path(settings.storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve(key: str) -> Path:
    root = _root()
    path = (root / key).resolve()
    # Refuse keys that would escape the storage root.
    if root not in path.parents and path != root:
        raise ValueError(f"Refusing to resolve key outside storage root: {key!r}")
    return path


def put_stream(key: str, source: BinaryIO) -> dict[str, object]:
    if not _use_s3():
        path = _resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with path.open("wb") as target:
            while chunk := source.read(_CHUNK):
                digest.update(chunk)
                size += len(chunk)
                target.write(chunk)
        return {"key": key, "size": size, "sha256": digest.hexdigest()}

    # Spool to a temp file rather than holding the upload in memory: these are finance
    # documents of unbounded size, and we need a second pass to upload after hashing.
    digest = hashlib.sha256()
    size = 0
    with tempfile.TemporaryFile() as spool:
        while chunk := source.read(_CHUNK):
            digest.update(chunk)
            size += len(chunk)
            spool.write(chunk)
        spool.seek(0)
        _s3().upload_fileobj(spool, _bucket(), key)
    return {"key": key, "size": size, "sha256": digest.hexdigest()}


def put_bytes(key: str, data: bytes) -> dict[str, object]:
    if _use_s3():
        _s3().put_object(Bucket=_bucket(), Key=key, Body=data)
    else:
        path = _resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return {"key": key, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def get_bytes(key: str) -> bytes:
    if _use_s3():
        return _s3().get_object(Bucket=_bucket(), Key=key)["Body"].read()
    return _resolve(key).read_bytes()


def path_for(key: str) -> Path:
    if _use_s3():
        raise RuntimeError(
            f"path_for({key!r}) has no meaning on object storage. Use get_bytes()."
        )
    return _resolve(key)


def exists(key: str) -> bool:
    if not _use_s3():
        return _resolve(key).exists()
    from botocore.exceptions import ClientError

    try:
        _s3().head_object(Bucket=_bucket(), Key=key)
        return True
    except ClientError:
        return False


def delete_key(key: str) -> None:
    """Remove one stored object. Missing is success - deleting twice is not an error.

    Used when a document is removed from a close: the record and the bytes go together,
    so a deleted document cannot leave an orphaned file behind in the bucket.
    """
    if not _use_s3():
        _resolve(key).unlink(missing_ok=True)
        return
    # S3 DeleteObject is already idempotent and returns 204 for a key that is not there.
    _s3().delete_object(Bucket=_bucket(), Key=key)


def delete_prefix(prefix: str) -> None:
    if not _use_s3():
        target = _resolve(prefix)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        return

    client = _s3()
    bucket = _bucket()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        # One call per key rather than a batch DeleteObjects. The batch form must carry a
        # Content-MD5 of the request body, which Storj enforces and botocore omits once
        # checksums are set to "when_required" above. Prefixes here hold one close's
        # documents, so the extra round trips are not worth a vendor-specific special case.
        for item in page.get("Contents", []):
            client.delete_object(Bucket=bucket, Key=item["Key"])
